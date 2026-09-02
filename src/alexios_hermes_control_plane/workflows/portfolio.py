import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from alexios_hermes_control_plane.activities.agents import run_judge, run_specialist
    from alexios_hermes_control_plane.activities.ledger import (
        ledger_complete_run,
        ledger_create_run,
        ledger_record_agent_result,
    )
    from alexios_hermes_control_plane.activities.notifications import notify_telegram
    from alexios_hermes_control_plane.schemas.common import (
        AgentResult,
        JudgeOutput,
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
            context: dict[str, object] = {
                "sites": request.sites,
                "mode": request.mode.value,
                "evidence": [],
                "note": "Stage 1 control-plane run; live evidence connectors are intentionally not enabled yet.",
            }
            roles = ["diagnostician", "strategist", "chief_of_staff"]
            tasks = [
                workflow.execute_activity(
                    run_specialist,
                    args=[role, request.objective, context],
                    start_to_close_timeout=agent_timeout,
                    retry_policy=retry,
                )
                for role in roles
            ]
            specialist_payloads = list(await asyncio.gather(*tasks))
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
                args=[request.objective, specialist_payloads],
                start_to_close_timeout=agent_timeout,
                retry_policy=retry,
            )
            judge_output = JudgeOutput.model_validate(judge_payload["judge_output"])
            judge_telemetry = dict(judge_payload["telemetry"])
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

            result = PortfolioRunResult(
                run_id=run_id,
                mode=request.mode,
                status="DONE",
                interventions=judge_output.interventions,
                specialist_results=specialist_results,
            )
            payload = result.model_dump(mode="json")
            await workflow.execute_activity(
                ledger_complete_run,
                args=[run_id, "DONE", payload],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            if workflow_input.notification_chat_id is not None:
                await workflow.execute_activity(
                    notify_telegram,
                    args=[workflow_input.notification_chat_id, _telegram_summary(result)],
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
                    args=[workflow_input.notification_chat_id, f"RUN FAILED {run_id}\n{str(exc)[:1200]}"],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            raise


def _telegram_summary(result: "PortfolioRunResult") -> str:
    lines = [f"RUN COMPLETE {result.run_id}", f"Mode: {result.mode.value}"]
    for item in result.interventions:
        lines.append(f"{item.rank}. {item.title} — confidence {item.confidence:.0%}")
        lines.append(f"   Target: {item.target}")
    lines.append("No production writes were performed.")
    return "\n".join(lines)
