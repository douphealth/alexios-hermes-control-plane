import asyncio
import logging
from datetime import UTC, datetime

from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.workflows.autonomous import AutonomousGrowthWorkflow

logger = logging.getLogger("ahcp.autonomous_scheduler")


def _cycle_id(interval_hours: int) -> str:
    now = datetime.now(UTC)
    bucket_seconds = interval_hours * 3600
    bucket = int(now.timestamp()) // bucket_seconds
    return f"autonomous-growth-{interval_hours}h-{bucket}"


async def run_cycle() -> str | None:
    settings = get_settings()
    if not settings.autonomous_growth_enabled:
        return None
    settings.assert_autonomous_write_safety()
    client = await Client.connect(
        settings.temporal_address,
        namespace=settings.temporal_namespace,
    )
    workflow_id = _cycle_id(settings.autonomous_growth_interval_hours)
    payload = {
        "objective": settings.autonomous_growth_objective,
        "mode": settings.autonomous_growth_mode,
        "notification_chat_id": settings.autonomous_notification_chat_id,
        "max_interventions": settings.autonomous_max_interventions_per_cycle,
        "max_mutations_per_site": settings.autonomous_max_mutations_per_site,
    }
    try:
        await client.start_workflow(
            AutonomousGrowthWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
    except WorkflowAlreadyStartedError:
        pass
    return workflow_id


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
            workflow_id = await run_cycle()
            if workflow_id:
                logger.info("autonomous cycle ensured workflow_id=%s", workflow_id)
        except Exception:
            logger.exception("autonomous growth scheduler cycle failed")
        await asyncio.sleep(60)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
