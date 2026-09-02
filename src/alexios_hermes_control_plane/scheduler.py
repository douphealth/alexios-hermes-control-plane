import asyncio
import logging
from datetime import UTC, datetime

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.schemas.common import PortfolioRunRequest, RunMode
from alexios_hermes_control_plane.services.temporal import WorkflowService

logger = logging.getLogger("ahcp.scheduler")


def _cycle_key(interval_hours: int) -> str:
    now = datetime.now(UTC)
    bucket_seconds = interval_hours * 3600
    bucket = int(now.timestamp()) // bucket_seconds
    return f"autonomous-growth:{interval_hours}h:{bucket}"


async def run_cycle() -> str | None:
    settings = get_settings()
    if not settings.autonomous_growth_enabled:
        return None
    settings.assert_autonomous_write_safety()
    service = WorkflowService(settings)
    request = PortfolioRunRequest(
        objective=settings.autonomous_growth_objective,
        mode=RunMode(settings.autonomous_growth_mode),
    )
    return await service.start_portfolio_run(
        request,
        notification_chat_id=settings.autonomous_notification_chat_id,
        idempotency_key=_cycle_key(settings.autonomous_growth_interval_hours),
    )


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
            run_id = await run_cycle()
            if run_id:
                logger.info("autonomous growth cycle ensured run_id=%s", run_id)
        except Exception:
            logger.exception("autonomous growth scheduler cycle failed")
        await asyncio.sleep(60)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
