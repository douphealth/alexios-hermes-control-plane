import asyncio
import logging
from datetime import UTC, datetime

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.workflows.autonomous import AutonomousGrowthWorkflow
from alexios_hermes_control_plane.workflows.measurement import OutcomeMeasurementWorkflow

logger = logging.getLogger("ahcp.autonomous_scheduler")


def _cycle_id(interval_hours: int) -> str:
    now = datetime.now(UTC)
    bucket_seconds = interval_hours * 3600
    bucket = int(now.timestamp()) // bucket_seconds
    return f"autonomous-growth-{interval_hours}h-{bucket}"


def _measurement_id() -> str:
    return f"autonomous-measurement-{datetime.now(UTC).date().isoformat()}"


async def _ensure_cycle() -> tuple[str | None, str | None, bool, bool]:
    """Ensure the current growth and measurement workflows exist exactly once on success.

    Completed workflows are never started again within the same interval/day. Failed,
    cancelled, or terminated workflows may be retried with the same business ID so the
    scheduler can self-heal without creating duplicate successful work.
    """
    settings = get_settings()
    if not settings.autonomous_growth_enabled:
        return None, None, False, False
    settings.assert_autonomous_write_safety()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )

    growth_id = _cycle_id(settings.autonomous_growth_interval_hours)
    growth_payload = {
        "objective": settings.autonomous_growth_objective,
        "mode": settings.autonomous_growth_mode,
        "notification_chat_id": settings.autonomous_notification_chat_id,
        "max_interventions": settings.autonomous_max_interventions_per_cycle,
        "max_mutations_per_site": settings.autonomous_max_mutations_per_site,
    }
    growth_started = False
    try:
        await client.start_workflow(
            AutonomousGrowthWorkflow.run,
            growth_payload,
            id=growth_id,
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        growth_started = True
    except WorkflowAlreadyStartedError:
        pass

    measurement_id = _measurement_id()
    measurement_started = False
    try:
        await client.start_workflow(
            OutcomeMeasurementWorkflow.run,
            {"notification_chat_id": settings.autonomous_notification_chat_id},
            id=measurement_id,
            task_queue=settings.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        measurement_started = True
    except WorkflowAlreadyStartedError:
        pass

    return growth_id, measurement_id, growth_started, measurement_started


async def run_cycle() -> tuple[str | None, str | None]:
    """Public idempotent cycle entrypoint used by operations and tests."""
    growth_id, measurement_id, _, _ = await _ensure_cycle()
    return growth_id, measurement_id


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    logger.info(
        "autonomous scheduler started enabled=%s interval_hours=%s mode=%s",
        settings.autonomous_growth_enabled,
        settings.autonomous_growth_interval_hours,
        settings.autonomous_growth_mode,
    )
    while True:
        try:
            growth_id, measurement_id, growth_started, measurement_started = await _ensure_cycle()
            if growth_id:
                logger.info(
                    "autonomous growth cycle ensured workflow_id=%s started=%s",
                    growth_id,
                    growth_started,
                )
            if measurement_id:
                logger.info(
                    "outcome measurement cycle ensured workflow_id=%s started=%s",
                    measurement_id,
                    measurement_started,
                )
        except Exception:
            logger.exception("autonomous scheduler cycle failed")
        await asyncio.sleep(60)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
