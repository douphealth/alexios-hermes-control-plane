from typing import Any

import asyncpg  # type: ignore[import-untyped]
from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.schemas.execution import WordPressMutation

_DEFAULT_COOLDOWN_DAYS = 7


@activity.defn
async def mutation_target_eligible(
    site_id: str,
    target_url: str,
    cooldown_days: int = _DEFAULT_COOLDOWN_DAYS,
) -> dict[str, Any]:
    """Reject recently changed URLs before an expensive implementer call."""
    if cooldown_days < 1:
        raise ValueError("cooldown_days must be >= 1")
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        row = await connection.fetchrow(
            """
            SELECT mutation_id, mutation_type, applied_at,
                   applied_at <= now() - ($3 * interval '1 day') AS cooldown_matured
            FROM autonomous_mutations
            WHERE site_id=$1
              AND rtrim(target_url, '/')=rtrim($2, '/')
              AND status='VALIDATED'
              AND rolled_back=false
            ORDER BY applied_at DESC
            LIMIT 1
            """,
            site_id,
            target_url,
            cooldown_days,
        )
    finally:
        await connection.close()
    if row is None:
        return {"eligible": True, "reason": "NO_PRIOR_VALIDATED_MUTATION"}
    if not bool(row["cooldown_matured"]):
        return {
            "eligible": False,
            "reason": "URL_COOLDOWN_ACTIVE",
            "cooldown_days": cooldown_days,
            "prior_mutation_id": str(row["mutation_id"]),
            "prior_mutation_type": str(row["mutation_type"]),
            "applied_at": row["applied_at"].isoformat(),
        }
    return {
        "eligible": True,
        "reason": "COOLDOWN_MATURED",
        "cooldown_days": cooldown_days,
        "prior_mutation_id": str(row["mutation_id"]),
    }


@activity.defn
async def mutation_candidate_eligible(
    mutation_payload: dict[str, Any],
    cooldown_days: int = _DEFAULT_COOLDOWN_DAYS,
) -> dict[str, Any]:
    """Reject an exact previously validated mutation and re-check URL cooldown before apply."""
    mutation = WordPressMutation.model_validate(mutation_payload)
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        duplicate = await connection.fetchrow(
            """
            SELECT mutation_id, applied_at
            FROM autonomous_mutations
            WHERE mutation_id=$1 AND status='VALIDATED' AND rolled_back=false
            LIMIT 1
            """,
            mutation.mutation_id,
        )
    finally:
        await connection.close()
    if duplicate is not None:
        return {
            "eligible": False,
            "reason": "EXACT_MUTATION_ALREADY_VALIDATED",
            "prior_mutation_id": str(duplicate["mutation_id"]),
            "applied_at": duplicate["applied_at"].isoformat(),
        }
    return await mutation_target_eligible(
        mutation.site_id,
        mutation.target_url,
        cooldown_days,
    )
