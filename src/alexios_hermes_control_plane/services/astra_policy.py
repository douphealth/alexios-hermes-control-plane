from typing import Any

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.schemas.common import AstraReviewOutput, JudgeOutput
from alexios_hermes_control_plane.services.scoring import decision_score


def escalation_reasons(judge_output: JudgeOutput, settings: Settings) -> list[str]:
    """Return deterministic reasons that justify spending an Astra call."""
    interventions = judge_output.interventions
    if not interventions:
        return []

    reasons: set[str] = set()
    if any(item.risk.strip().upper().startswith("HIGH") for item in interventions):
        reasons.add("HIGH_RISK")

    if len(interventions) >= 2:
        first = interventions[0].decision_score
        second = interventions[1].decision_score
        if first is not None and second is not None:
            if abs(first - second) <= settings.astra_ambiguity_score_gap:
                reasons.add("AMBIGUOUS_TOP_DECISION")

    for item in interventions:
        if (
            item.impact >= settings.astra_high_impact_threshold
            and item.confidence < settings.astra_low_confidence_threshold
        ):
            reasons.add("HIGH_IMPACT_LOW_CONFIDENCE")
        if (
            item.revenue_alignment >= settings.astra_high_revenue_threshold
            and item.confidence < settings.astra_low_confidence_threshold
        ):
            reasons.add("HIGH_REVENUE_LOW_CONFIDENCE")

    return sorted(reasons)


def budget_allows(usage: dict[str, Any], settings: Settings) -> tuple[bool, str]:
    calls = int(usage.get("calls") or 0)
    total_tokens = int(usage.get("total_tokens") or 0)
    if calls >= settings.astra_max_calls_per_24h:
        return False, "ASTRA_DAILY_CALL_BUDGET_EXHAUSTED"
    if total_tokens >= settings.astra_max_total_tokens_per_24h:
        return False, "ASTRA_DAILY_TOKEN_BUDGET_EXHAUSTED"
    return True, "ASTRA_BUDGET_AVAILABLE"


def apply_astra_review(judge_output: JudgeOutput, review: AstraReviewOutput) -> JudgeOutput:
    """Apply a bounded review: Astra may only drop or reduce confidence, never invent work."""
    existing_ranks = {item.rank for item in judge_output.interventions}
    review_ranks = {item.rank for item in review.decisions}
    unknown_ranks = review_ranks - existing_ranks
    if unknown_ranks:
        raise ValueError(f"Astra review referenced unknown ranks: {sorted(unknown_ranks)}")

    by_rank = {item.rank: item for item in review.decisions}
    kept = []
    for intervention in judge_output.interventions:
        decision = by_rank.get(intervention.rank)
        if decision is not None and decision.verdict == "DROP":
            continue

        multiplier = decision.confidence_multiplier if decision is not None else 1.0
        confidence = round(intervention.confidence * multiplier, 4)
        score = decision_score(
            impact=intervention.impact,
            confidence=confidence,
            revenue_alignment=intervention.revenue_alignment,
            effort=intervention.effort,
            reversibility=intervention.reversibility,
            time_to_signal=intervention.time_to_signal,
        )
        kept.append(
            intervention.model_copy(update={"confidence": confidence, "decision_score": score})
        )

    ranked = sorted(kept, key=lambda item: (item.decision_score or 0), reverse=True)
    reranked = [item.model_copy(update={"rank": index}) for index, item in enumerate(ranked, 1)]
    return JudgeOutput(interventions=reranked)
