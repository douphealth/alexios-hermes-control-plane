import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from temporalio.client import Client
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


async def run_cycle() -> tuple[str | None, str | None]:
    settings = get_settings()
    if not settings.autonomous_growth_enabled:
        return None, None
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
    with suppress(WorkflowAlreadyStartedError):
        await client.start_workflow(
            AutonomousGrowthWorkflow.run,
            growth_payload,
            id=growth_id,
            task_queue=settings.temporal_task_queue,
        )

    measurement_id = _measurement_id()
    with suppress(WorkflowAlreadyStartedError):
        await client.start_workflow(
            OutcomeMeasurementWorkflow.run,
            {"notification_chat_id": settings.autonomous_notification_chat_id},
            id=measurement_id,
            task_queue=settings.temporal_task_queue,
        )
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
            growth_id, measurement_id = await run_cycle()
            if growth_id:
                logger.info("autonomous growth cycle ensured workflow_id=%s", growth_id)
            if measurement_id:
                logger.info("outcome measurement sweep ensured workflow_id=%s", measurement_id)
        except Exception:
            logger.exception("autonomous scheduler cycle failed")
        await asyncio.sleep(60)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
