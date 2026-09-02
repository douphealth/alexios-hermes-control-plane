import asyncio
from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from alexios_hermes_control_plane.activities.agents import (
        run_judge,
        run_specialist,
        run_verifier,
    )
    from alexios_hermes_control_plane.activities.context import (
        load_context_config,
        registry_configured_roles,
    )
    from alexios_hermes_control_plane.activities.evidence import collect_gsc_evidence
    from alexios_hermes_control_plane.activities.ledger import (
        ledger_complete_run,
        ledger_create_run,
        ledger_recent_feedback,
        ledger_recent_runs,
        ledger_record_agent_result,
    )
    from alexios_hermes_control_plane.activities.notifications import notify_telegram
    from alexios_hermes_control_plane.prompts import SPECIALIST_ROLES
    from alexios_hermes_control_plane.prompts.portfolio_context import (
        format_feedback_memory,
        format_operating_rules,
        format_recent_runs,
        format_sites,
    )
    from alexios_hermes_control_plane.schemas.common import (
        AgentResult,
        JudgeOutput,
        PortfolioRunRequest,
        PortfolioRunResult,
        PortfolioWorkflowInput,
    )


@workflow.defn
class PortfolioOptimizationWorkflow:
    @workflow.run
    async def run(self, input_payload: dict[str, object]) -> dict[str, object]:
        workflow_input = PortfolioWorkflowInput.model_validate(input_payload)
        request = workflow_input.request
        run_id = workflow.info().workflow_id
        agent_timeout = timedelta(minutes=5)
        retry = RetryPolicy(maximum_attempts=2)

        await workflow.execute_activity(
            ledger_create_run,
            args=[run_id, request.objective, request.mode.value],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=retry,
        )

        try:
            context = await self._build_context(request)
            history = await self._load_history()

            specialist_payloads = await self._run_specialists(
                request.objective, context, history, retry, agent_timeout
            )
            specialist_payloads = await self._run_verifier_gate(
                request.objective, specialist_payloads, context, retry, agent_timeout
            )
            specialist_results = [AgentResult.model_validate(item) for item in specialist_payloads]

            for result in specialist_results:
                await workflow.execute_activity(
                    ledger_record_agent_result,
                    args=[run_id, result.model_dump(mode="json")],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )

            judge_payload = await workflow.execute_activity(
                run_judge,
                args=[request.objective, specialist_payloads, context],
                start_to_close_timeout=agent_timeout,
                retry_policy=retry,
            )
            judge_output = JudgeOutput.model_validate(judge_payload["judge_output"])
            judge_telemetry = cast(dict[str, object], judge_payload["telemetry"])
            judge_record: dict[str, object] = {
                **judge_telemetry,
                "status": "SUCCESS",
                "summary": f"Selected {len(judge_output.interventions)} interventions",
                "findings": [],
                "evidence_ids": [],
                "assumptions": [],
                "error": None,
            }
            await workflow.execute_activity(
                ledger_record_agent_result,
                args=[run_id, judge_record],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )

            status = "DONE" if judge_output.interventions else "NEEDS_VERIFICATION_OR_DATA"
            run_result = PortfolioRunResult(
                run_id=run_id,
                mode=request.mode,
                status=status,
                interventions=judge_output.interventions,
                specialist_results=specialist_results,
            )
            payload = run_result.model_dump(mode="json")
            await workflow.execute_activity(
                ledger_complete_run,
                args=[run_id, status, payload],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            if workflow_input.notification_chat_id is not None:
                await workflow.execute_activity(
                    notify_telegram,
                    args=[workflow_input.notification_chat_id, _telegram_summary(run_result)],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            return payload
        except Exception as exc:
            failure = {"run_id": run_id, "status": "FAILED", "error": str(exc)[:2000]}
            await workflow.execute_activity(
                ledger_complete_run,
                args=[run_id, "FAILED", failure],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            if workflow_input.notification_chat_id is not None:
                await workflow.execute_activity(
                    notify_telegram,
                    args=[
                        workflow_input.notification_chat_id,
                        f"RUN FAILED {run_id}\n{str(exc)[:1200]}",
                    ],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            raise

    async def _build_context(self, request: PortfolioRunRequest) -> dict[str, object]:
        config = await workflow.execute_activity(
            load_context_config,
            args=[request.sites],
            start_to_close_timeout=timedelta(seconds=15),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        recent_runs = cast(
            list[dict[str, Any]],
            await workflow.execute_activity(
                ledger_recent_runs,
                args=[10],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        feedback_memory = cast(
            list[dict[str, Any]],
            await workflow.execute_activity(
                ledger_recent_feedback,
                args=[50],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        config_sites = cast(list[dict[str, str]], config["sites"])
        config_rules = cast(list[str], config["operating_rules"])
        evidence_result = cast(
            dict[str, object],
            await workflow.execute_activity(
                collect_gsc_evidence,
                args=[config_sites],
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ),
        )
        evidence = cast(list[dict[str, object]], evidence_result.get("evidence", []))
        note = str(evidence_result.get("note", "GSC evidence collection returned no note."))
        errors = cast(list[str], evidence_result.get("errors", []))
        if errors:
            note += " Connector errors: " + " | ".join(errors[:10])
        return {
            "sites": config_sites,
            "sites_display": format_sites(config_sites),
            "mode": request.mode.value,
            "evidence": evidence,
            "evidence_note": note,
            "operating_rules": config_rules,
            "operating_rules_display": format_operating_rules(tuple(config_rules)),
            "recent_runs": recent_runs,
            "recent_runs_display": format_recent_runs(recent_runs),
            "feedback_memory": feedback_memory,
            "feedback_memory_display": format_feedback_memory(feedback_memory),
        }

    async def _load_history(self) -> dict[str, object]:
        return {}

    async def _run_specialists(
        self,
        objective: str,
        context: dict[str, object],
        history: dict[str, object],
        retry: RetryPolicy,
        agent_timeout: timedelta,
    ) -> list[dict[str, object]]:
        tasks = [
            workflow.execute_activity(
                run_specialist,
                args=[role, objective, context],
                start_to_close_timeout=agent_timeout,
                retry_policy=retry,
            )
            for role in SPECIALIST_ROLES
        ]
        return list(await asyncio.gather(*tasks))

    async def _run_verifier_gate(
        self,
        objective: str,
        specialist_payloads: list[dict[str, object]],
        context: dict[str, object],
        retry: RetryPolicy,
        agent_timeout: timedelta,
    ) -> list[dict[str, object]]:
        """Stamp verifier verdicts; unavailable verification leaves findings UNVERIFIED.

        The workflow remains available when the verifier is absent, while run_judge enforces
        fail-closed decision eligibility by removing UNVERIFIED/UNGROUNDED findings in code.
        """
        roles = cast(
            list[str],
            await workflow.execute_activity(
                registry_configured_roles,
                args=[],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=2),
            ),
        )
        if "verifier" not in roles:
            return specialist_payloads
        try:
            verifier_payload = await workflow.execute_activity(
                run_verifier,
                args=[objective, specialist_payloads, context],
                start_to_close_timeout=agent_timeout,
                retry_policy=retry,
            )
        except Exception:
            return specialist_payloads

        verifier_output = cast(dict[str, object], verifier_payload["verifier_output"])
        raw_verdicts = cast(list[object], verifier_output.get("verdicts", []))
        by_finding: dict[str, str] = {}
        for verdict in raw_verdicts:
            if isinstance(verdict, dict):
                by_finding[str(verdict.get("finding_id"))] = str(verdict.get("verdict"))
        merged: list[dict[str, object]] = []
        for payload in specialist_payloads:
            findings = payload.get("findings", [])
            if isinstance(findings, list):
                for finding in findings:
                    if isinstance(finding, dict):
                        fid = str(finding.get("finding_id"))
                        if fid in by_finding:
                            finding["verification"] = by_finding[fid]
            merged.append(payload)
        return merged


def _telegram_summary(result: "PortfolioRunResult") -> str:
    lines = [f"RUN COMPLETE {result.run_id}", f"Mode: {result.mode.value}", f"Status: {result.status}"]
    if not result.interventions:
        lines.append("No intervention cleared the deterministic evidence/verification gate.")
    for item in result.interventions:
        score = f" | score {item.decision_score:.1f}" if item.decision_score is not None else ""
        lines.append(f"{item.rank}. {item.title} — confidence {item.confidence:.0%}{score}")
        lines.append(f"   Target: {item.target}")
        lines.append(f"   Signal: {item.expected_signal}")
    lines.append(
        "Reply with a verdict to train future runs: "
        "ADOPTED / REJECTED / EXECUTED_VERIFIED / EXECUTED_NO_SIGNAL / PARTIAL"
    )
    lines.append("No production writes were performed.")
    return "\n".join(lines)
