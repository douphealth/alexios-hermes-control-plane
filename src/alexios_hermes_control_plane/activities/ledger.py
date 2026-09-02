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
async def ledger_record_evidence(run_id: str, items: list[dict[str, object]]) -> None:
    await _get_ledger().record_evidence(run_id, items)


@activity.defn
async def ledger_complete_run(run_id: str, status: str, result: dict[str, object]) -> None:
    await _get_ledger().complete_run(run_id, status, result)


@activity.defn
async def ledger_recent_runs(limit: int) -> list[dict[str, object]]:
    return await _get_ledger().recent_runs(limit)


@activity.defn
async def ledger_recent_feedback(limit: int) -> list[dict[str, object]]:
    return await _get_ledger().recent_feedback(limit)


@activity.defn
async def ledger_record_feedback(
    run_id: str, intervention_rank: int, verdict: str, outcome_note: str | None
) -> None:
    await _get_ledger().record_feedback(run_id, intervention_rank, verdict, outcome_note)
