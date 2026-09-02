from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from alexios_hermes_control_plane.activities.implementation import run_implementer
    from alexios_hermes_control_plane.activities.notifications import notify_telegram
    from alexios_hermes_control_plane.activities.outcomes import (
        capture_gsc_baselines,
        record_autonomous_mutation,
    )
    from alexios_hermes_control_plane.activities.wordpress import (
        wordpress_apply_mutation,
        wordpress_read_target,
        wordpress_rollback_mutation,
        wordpress_validate_mutation,
    )
    from alexios_hermes_control_plane.activities.wordpress_registry import wordpress_resolve_site
    from alexios_hermes_control_plane.schemas.common import (
        PortfolioRunRequest,
        PortfolioRunResult,
        PortfolioWorkflowInput,
        RunMode,
    )
    from alexios_hermes_control_plane.schemas.execution import ImplementationPlan, MutationReceipt
    from alexios_hermes_control_plane.workflows.portfolio import PortfolioOptimizationWorkflow


@workflow.defn
class AutonomousGrowthWorkflow:
    @workflow.run
    async def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        objective = str(input_payload["objective"])
        requested_mode = RunMode(str(input_payload.get("mode", "DRAFT")))
        notification_chat_id = cast(int | None, input_payload.get("notification_chat_id"))
        max_interventions = int(input_payload.get("max_interventions", 3))
        max_mutations_per_site = int(input_payload.get("max_mutations_per_site", 1))
        workflow_id = workflow.info().workflow_id

        analysis_request = PortfolioRunRequest(objective=objective, mode=RunMode.READ_ONLY)
        analysis_input = PortfolioWorkflowInput(request=analysis_request, notification_chat_id=None)
        analysis_payload = await workflow.execute_child_workflow(
            PortfolioOptimizationWorkflow.run,
            analysis_input.model_dump(mode="json"),
            id=f"{workflow_id}-analysis",
            task_queue=workflow.info().task_queue,
        )
        analysis = PortfolioRunResult.model_validate(analysis_payload)

        plans: list[dict[str, Any]] = []
        receipts: list[dict[str, Any]] = []

        # READ_ONLY is a pure intelligence cycle. It must not require WordPress
        # credentials, resolve targets, call the implementer, or touch live sites.
        if requested_mode == RunMode.READ_ONLY:
            result = {
                "workflow_id": workflow_id,
                "mode": requested_mode.value,
                "analysis": analysis.model_dump(mode="json"),
                "implementation_plans": plans,
                "mutation_receipts": receipts,
                "production_writes_attempted": False,
            }
            if notification_chat_id is not None:
                message = (
                    f"AUTONOMOUS GROWTH CYCLE {workflow_id}\n"
                    f"Analysis: {analysis.status}\n"
                    "Plans: 0\n"
                    "Validated mutations: 0\n"
                    "Rolled back: 0\n"
                    "Mode: READ_ONLY"
                )
                await workflow.execute_activity(
                    notify_telegram,
                    args=[notification_chat_id, message],
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            return result

        site_mutations: dict[str, int] = {}
        retry = RetryPolicy(maximum_attempts=2)

        if analysis.status == "DONE":
            for intervention in analysis.interventions[:max_interventions]:
                try:
                    resolved = cast(
                        dict[str, Any],
                        await workflow.execute_activity(
                            wordpress_resolve_site,
                            args=[intervention.target],
                            start_to_close_timeout=timedelta(seconds=30),
                            retry_policy=retry,
                        ),
                    )
                    site_id = str(resolved["site_id"])
                    if site_mutations.get(site_id, 0) >= max_mutations_per_site:
                        continue
                    snapshot = cast(
                        dict[str, Any],
                        await workflow.execute_activity(
                            wordpress_read_target,
                            args=[site_id, intervention.target],
                            start_to_close_timeout=timedelta(minutes=1),
                            retry_policy=retry,
                        ),
                    )
                    implementer_payload = cast(
                        dict[str, Any],
                        await workflow.execute_activity(
                            run_implementer,
                            args=[intervention.model_dump(mode="json"), snapshot],
                            start_to_close_timeout=timedelta(minutes=5),
                            retry_policy=retry,
                        ),
                    )
                    plan = ImplementationPlan.model_validate(implementer_payload["plan"])
                    plans.append(
                        {
                            "intervention_rank": intervention.rank,
                            "intervention_title": intervention.title,
                            "target": intervention.target,
                            "plan": plan.model_dump(mode="json"),
                            "telemetry": implementer_payload.get("telemetry", {}),
                        }
                    )
                    if requested_mode == RunMode.DRAFT:
                        continue

                    for mutation in plan.mutations:
                        if site_mutations.get(site_id, 0) >= max_mutations_per_site:
                            break
                        baseline: dict[str, Any] = {}
                        try:
                            baseline = cast(
                                dict[str, Any],
                                await workflow.execute_activity(
                                    capture_gsc_baselines,
                                    args=[site_id, mutation.target_url],
                                    start_to_close_timeout=timedelta(minutes=2),
                                    retry_policy=retry,
                                ),
                            )
                        except Exception:
                            baseline = {}

                        mutation_payload = mutation.model_dump(mode="json")
                        apply_args = [mutation_payload, snapshot, requested_mode.value]
                        applied_payload = cast(
                            dict[str, Any],
                            await workflow.execute_activity(
                                wordpress_apply_mutation,
                                args=apply_args,
                                start_to_close_timeout=timedelta(minutes=1),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                            ),
                        )
                        applied = MutationReceipt.model_validate(applied_payload)
                        try:
                            validated_payload = cast(
                                dict[str, Any],
                                await workflow.execute_activity(
                                    wordpress_validate_mutation,
                                    args=[mutation_payload, applied_payload],
                                    start_to_close_timeout=timedelta(minutes=1),
                                    retry_policy=retry,
                                ),
                            )
                            validated = MutationReceipt.model_validate(validated_payload)
                            if validated.status != "VALIDATED":
                                error = validated.validation_error or "validation failed"
                                raise RuntimeError(error)
                            await workflow.execute_activity(
                                record_autonomous_mutation,
                                args=[
                                    workflow_id,
                                    mutation_payload,
                                    validated.model_dump(mode="json"),
                                    baseline,
                                ],
                                start_to_close_timeout=timedelta(seconds=30),
                                retry_policy=RetryPolicy(maximum_attempts=3),
                            )
                            receipts.append(validated.model_dump(mode="json"))
                            site_mutations[site_id] = site_mutations.get(site_id, 0) + 1
                        except Exception as exc:
                            rolled_back = cast(
                                dict[str, Any],
                                await workflow.execute_activity(
                                    wordpress_rollback_mutation,
                                    args=[applied.model_dump(mode="json")],
                                    start_to_close_timeout=timedelta(minutes=1),
                                    retry_policy=RetryPolicy(maximum_attempts=3),
                                ),
                            )
                            rolled_back["validation_error"] = str(exc)[:1000]
                            await workflow.execute_activity(
                                record_autonomous_mutation,
                                args=[workflow_id, mutation_payload, rolled_back, baseline],
                                start_to_close_timeout=timedelta(seconds=30),
                                retry_policy=RetryPolicy(maximum_attempts=3),
                            )
                            receipts.append(rolled_back)
                except Exception as exc:
                    plans.append(
                        {
                            "intervention_rank": intervention.rank,
                            "intervention_title": intervention.title,
                            "target": intervention.target,
                            "status": "SKIPPED_OR_FAILED",
                            "error": f"{type(exc).__name__}: {str(exc)[:1200]}",
                        }
                    )

        result = {
            "workflow_id": workflow_id,
            "mode": requested_mode.value,
            "analysis": analysis.model_dump(mode="json"),
            "implementation_plans": plans,
            "mutation_receipts": receipts,
            "production_writes_attempted": requested_mode == RunMode.PRODUCTION_APPROVED,
        }
        if notification_chat_id is not None:
            validated_count = sum(1 for item in receipts if item.get("status") == "VALIDATED")
            rolled_back_count = sum(1 for item in receipts if item.get("rolled_back") is True)
            message = (
                f"AUTONOMOUS GROWTH CYCLE {workflow_id}\n"
                f"Analysis: {analysis.status}\n"
                f"Plans: {len(plans)}\n"
                f"Validated mutations: {validated_count}\n"
                f"Rolled back: {rolled_back_count}\n"
                f"Mode: {requested_mode.value}"
            )
            await workflow.execute_activity(
                notify_telegram,
                args=[notification_chat_id, message],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        return result
