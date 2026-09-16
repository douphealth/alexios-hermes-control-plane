import json
from copy import deepcopy
from typing import Any

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry
from alexios_hermes_control_plane.schemas.common import AstraReviewOutput, JudgeOutput
from alexios_hermes_control_plane.services.astra_policy import (
    apply_astra_review,
    budget_allows,
    escalation_reasons,
)
from alexios_hermes_control_plane.services.ledger import Ledger

_ASTRA_PROMPT_VERSION = "2026-09-16.1"
_ASTRA_REVIEW_PROMPT = """
You are the scarce escalation reviewer in Alexios Hermes Intelligence OS.

You receive ONLY an already-verified, already-ranked set of at most three interventions plus the
small evidence subset directly cited by those interventions. Do not perform discovery, propose new
work, rewrite content, or repeat the specialist analysis.

Your sole job is to prevent expensive mistakes when the deterministic router found ambiguity or
high stakes. For each supplied intervention you may:
- KEEP it with confidence_multiplier 1.0 when the evidence and reasoning are adequate;
- KEEP it with confidence_multiplier between 0.5 and 0.99 when confidence should be discounted;
- DROP it when the evidence does not justify the action or risk.

Never increase confidence. Never invent evidence, URLs, metrics, interventions, or implementation
steps. Judge only from supplied evidence. Keep reasons short and decision-useful. Silence is cheaper
than speculation.
""".strip()


def _compact_evidence(
    context: dict[str, Any], judge_output: JudgeOutput, max_items: int, row_limit: int
) -> list[dict[str, Any]]:
    wanted = {
        evidence_id
        for intervention in judge_output.interventions
        for evidence_id in intervention.evidence_ids
    }
    raw = context.get("evidence", [])
    if not isinstance(raw, list):
        return []

    compact: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or str(item.get("evidence_id")) not in wanted:
            continue
        copied = deepcopy(item)
        payload = copied.get("payload")
        if isinstance(payload, dict):
            rows = payload.get("rows")
            if isinstance(rows, list):
                payload["rows"] = rows[:row_limit]
                payload["rows_truncated"] = max(0, len(rows) - row_limit)
        compact.append(copied)
        if len(compact) >= max_items:
            break
    return compact


async def review_with_astra_if_needed(
    objective: str, judge_output_payload: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    """Escalate only ambiguous/high-stakes decisions and hard-cap rolling usage."""
    settings = get_settings()
    judge_output = JudgeOutput.model_validate(judge_output_payload)
    reasons = escalation_reasons(judge_output, settings)
    skipped = {
        "invoked": False,
        "reasons": reasons,
        "judge_output": judge_output.model_dump(mode="json"),
        "review": None,
        "telemetry": None,
    }
    if not settings.astra_escalation_enabled:
        return {**skipped, "skip_reason": "ASTRA_DISABLED"}
    if not reasons:
        return {**skipped, "skip_reason": "NO_ESCALATION_TRIGGER"}

    registry = ModelRegistry(settings)
    if "astra_reviewer" not in registry.configured_roles():
        return {**skipped, "skip_reason": "ASTRA_NOT_CONFIGURED"}

    ledger = Ledger(settings.database_url)
    try:
        usage = await ledger.agent_usage_last_hours("astra_reviewer", 24)
        allowed, budget_reason = budget_allows(usage, settings)
        if not allowed:
            return {**skipped, "skip_reason": budget_reason, "rolling_usage": usage}

        evidence = _compact_evidence(
            context,
            judge_output,
            settings.astra_max_evidence_items,
            settings.astra_evidence_row_limit,
        )
        target = registry.get("astra_reviewer")
        user_payload = {
            "objective": objective,
            "escalation_reasons": reasons,
            "interventions": judge_output.model_dump(mode="json")["interventions"],
            "evidence": evidence,
        }
        invocation = await target.adapter.invoke_structured(
            model=target.model,
            system=_ASTRA_REVIEW_PROMPT,
            user=json.dumps(user_payload, default=str, separators=(",", ":")),
            response_model=AstraReviewOutput,
            prompt_cache_key=f"ahcp:astra-review:{_ASTRA_PROMPT_VERSION}",
        )
        review = AstraReviewOutput.model_validate(invocation.output)
        reviewed = apply_astra_review(judge_output, review)
        telemetry = {
            "agent": "astra_reviewer",
            "model": target.model,
            "prompt_version": _ASTRA_PROMPT_VERSION,
            "provider_request_id": invocation.provider_request_id,
            "latency_ms": invocation.latency_ms,
            "input_tokens": invocation.input_tokens,
            "cached_input_tokens": invocation.cached_input_tokens,
            "output_tokens": invocation.output_tokens,
            "total_tokens": invocation.total_tokens,
            "status": "SUCCESS",
            "summary": review.summary,
            "findings": [],
            "evidence_ids": sorted(
                {
                    evidence_id
                    for intervention in judge_output.interventions
                    for evidence_id in intervention.evidence_ids
                }
            ),
            "assumptions": [],
            "error": None,
            "escalation_reasons": reasons,
            "rolling_usage_before_call": usage,
        }
        await ledger.record_agent_result(activity.info().workflow_id, telemetry)
        return {
            "invoked": True,
            "reasons": reasons,
            "skip_reason": None,
            "judge_output": reviewed.model_dump(mode="json"),
            "review": review.model_dump(mode="json"),
            "telemetry": telemetry,
            "rolling_usage": usage,
        }
    finally:
        await ledger.close()
