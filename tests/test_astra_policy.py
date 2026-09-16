import pytest
from pydantic import ValidationError

from alexios_hermes_control_plane.config import Settings
from alexios_hermes_control_plane.schemas.common import (
    AstraReviewDecision,
    AstraReviewOutput,
    Intervention,
    JudgeOutput,
)
from alexios_hermes_control_plane.services.astra_policy import (
    apply_astra_review,
    budget_allows,
    escalation_reasons,
)


def _intervention(
    rank: int,
    *,
    score: float,
    confidence: float = 0.9,
    impact: int = 7,
    revenue_alignment: int = 7,
    risk: str = "LOW — one page",
) -> Intervention:
    return Intervention(
        rank=rank,
        title=f"Action {rank}",
        target=f"https://example.com/{rank}/",
        action="Apply reversible technical improvement",
        impact=impact,
        confidence=confidence,
        revenue_alignment=revenue_alignment,
        effort=2,
        risk=risk,
        reversibility=9,
        time_to_signal=4,
        evidence_ids=[f"ev-{rank}"],
        expected_signal="Clicks increase within 14 days",
        decision_score=score,
    )


def test_escalates_ambiguous_top_decision() -> None:
    settings = Settings(_env_file=None, astra_ambiguity_score_gap=6.0)
    output = JudgeOutput(
        interventions=[
            _intervention(1, score=82.0),
            _intervention(2, score=78.0),
        ]
    )
    assert "AMBIGUOUS_TOP_DECISION" in escalation_reasons(output, settings)


def test_escalates_high_risk_and_low_confidence_high_impact() -> None:
    settings = Settings(_env_file=None)
    output = JudgeOutput(
        interventions=[
            _intervention(
                1,
                score=80.0,
                confidence=0.70,
                impact=9,
                revenue_alignment=9,
                risk="HIGH — sitewide canonical rules",
            )
        ]
    )
    reasons = escalation_reasons(output, settings)
    assert "HIGH_RISK" in reasons
    assert "HIGH_IMPACT_LOW_CONFIDENCE" in reasons
    assert "HIGH_REVENUE_LOW_CONFIDENCE" in reasons


def test_clear_low_risk_decision_does_not_escalate() -> None:
    settings = Settings(_env_file=None)
    output = JudgeOutput(interventions=[_intervention(1, score=88.0)])
    assert escalation_reasons(output, settings) == []


def test_budget_blocks_calls_and_tokens_independently() -> None:
    settings = Settings(
        _env_file=None,
        astra_max_calls_per_24h=2,
        astra_max_total_tokens_per_24h=80_000,
    )
    assert budget_allows({"calls": 1, "total_tokens": 79_999}, settings)[0] is True
    assert budget_allows({"calls": 2, "total_tokens": 1}, settings) == (
        False,
        "ASTRA_DAILY_CALL_BUDGET_EXHAUSTED",
    )
    assert budget_allows({"calls": 1, "total_tokens": 80_000}, settings) == (
        False,
        "ASTRA_DAILY_TOKEN_BUDGET_EXHAUSTED",
    )


def test_astra_can_only_reduce_confidence_or_drop() -> None:
    output = JudgeOutput(
        interventions=[
            _intervention(1, score=82.0, confidence=0.90),
            _intervention(2, score=70.0, confidence=0.80),
        ]
    )
    review = AstraReviewOutput(
        summary="One action is insufficiently justified.",
        decisions=[
            AstraReviewDecision(
                rank=1,
                verdict="KEEP",
                confidence_multiplier=0.8,
                reason="Evidence supports direction but not magnitude.",
            ),
            AstraReviewDecision(
                rank=2,
                verdict="DROP",
                confidence_multiplier=1.0,
                reason="Risk is not justified by the evidence.",
            ),
        ],
    )
    reviewed = apply_astra_review(output, review)
    assert len(reviewed.interventions) == 1
    assert reviewed.interventions[0].rank == 1
    assert reviewed.interventions[0].confidence == pytest.approx(0.72)


def test_schema_forbids_confidence_increase() -> None:
    with pytest.raises(ValidationError):
        AstraReviewDecision(
            rank=1,
            verdict="KEEP",
            confidence_multiplier=1.01,
            reason="Not allowed",
        )


def test_review_cannot_reference_unknown_rank() -> None:
    output = JudgeOutput(interventions=[_intervention(1, score=82.0)])
    review = AstraReviewOutput(
        summary="Invalid review",
        decisions=[
            AstraReviewDecision(
                rank=2,
                verdict="KEEP",
                confidence_multiplier=1.0,
                reason="Unknown intervention",
            )
        ],
    )
    with pytest.raises(ValueError, match="unknown ranks"):
        apply_astra_review(output, review)
