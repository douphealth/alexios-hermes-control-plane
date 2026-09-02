from datetime import timedelta
from typing import Any, cast

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from alexios_hermes_control_plane.activities.outcomes import (
        list_due_measurements,
        measure_and_record_outcome,
    )
    from alexios_hermes_control_plane.activities.notifications import notify_telegram


@workflow.defn
class OutcomeMeasurementWorkflow:
    @workflow.run
    async def run(self, input_payload: dict[str, Any]) -> dict[str, Any]:
        notification_chat_id = cast(int | None, input_payload.get("notification_chat_id"))
        due = cast(
            list[dict[str, Any]],
            await workflow.execute_activity(
                list_due_measurements,
                args=[50],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            ),
        )
        measured: list[dict[str, Any]] = []
        failed: list[dict[str, str]] = []
        for item in due:
            try:
                result = cast(
                    dict[str, Any],
                    await workflow.execute_activity(
                        measure_and_record_outcome,
                        args=[item],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=RetryPolicy(maximum_attempts=2),
                    ),
                )
                measured.append(result)
            except Exception as exc:
                failed.append(
                    {
                        "mutation_id": str(item.get("mutation_id", "unknown")),
                        "error": f"{type(exc).__name__}: {str(exc)[:600]}",
                    }
                )
        if notification_chat_id is not None and (measured or failed):
            message = (
                "HERMES OUTCOME MEASUREMENT\n"
                f"Measured: {len(measured)}\n"
                f"Failed: {len(failed)}\n"
                "Windows: 7/14/28-day GSC outcomes"
            )
            await workflow.execute_activity(
                notify_telegram,
                args=[notification_chat_id, message],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        return {"measured": measured, "failed": failed, "due_count": len(due)}
