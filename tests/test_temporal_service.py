import pytest

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.schemas.common import PortfolioRunRequest, RunMode
from alexios_hermes_control_plane.services.temporal import WorkflowService, _workflow_id


def test_idempotency_workflow_id_is_stable() -> None:
    assert _workflow_id("abc") == _workflow_id("abc")
    assert _workflow_id("abc") != _workflow_id("def")


@pytest.mark.asyncio
async def test_production_mode_fails_before_temporal_connection() -> None:
    settings = Settings(_env_file=None, allow_production_writes=False)
    service = WorkflowService(settings)
    with pytest.raises(PermissionError):
        await service.start_portfolio_run(
            PortfolioRunRequest(objective="write", mode=RunMode.PRODUCTION_APPROVED)
        )
