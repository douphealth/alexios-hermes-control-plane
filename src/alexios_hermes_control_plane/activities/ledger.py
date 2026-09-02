from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.services.ledger import Ledger

_ledger: Ledger | None = None


def _get_ledger() -> Ledger:
    global _ledger
    if _ledger is None:
        _ledger = Ledger(get_settings().database_url)
    return _ledger


@activity.defn
async def ledger_create_run(run_id: str, objective: str, mode: str) -> None:
    await _get_ledger().create_run(run_id, objective, mode)


@activity.defn
async def ledger_record_agent_result(run_id: str, result: dict[str, object]) -> None:
    await _get_ledger().record_agent_result(run_id, result)


@activity.defn
async def ledger_complete_run(run_id: str, status: str, result: dict[str, object]) -> None:
    await _get_ledger().complete_run(run_id, status, result)
