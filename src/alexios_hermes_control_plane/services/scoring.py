"""Deterministic intervention scoring.

The judge model estimates the fields; code computes the tradeoff score. Deterministic
scoring in code beats vibes: the same inputs always produce the same ranking signal,
and prompt-version experiments become comparable across runs.
"""

from pydantic import BaseModel, Field


class ScoreInputs(BaseModel):
    impact: int = Field(ge=0, le=10)
    confidence: float = Field(ge=0, le=1)
    revenue_alignment: int = Field(ge=0, le=10)
    effort: int = Field(ge=0, le=10)
    reversibility: int = Field(ge=0, le=10)
    time_to_signal: int = Field(ge=0, le=10)


def decision_score(
    *,
    impact: int,
    confidence: float,
    revenue_alignment: int,
    effort: int,
    reversibility: int,
    time_to_signal: int,
) -> float:
    """Higher is better. Rewards impact, confidence, revenue alignment, reversibility;
    penalizes effort and time-to-signal. Always in [0, 100]."""
    inputs = ScoreInputs(
        impact=impact,
        confidence=confidence,
        revenue_alignment=revenue_alignment,
        effort=effort,
        reversibility=reversibility,
        time_to_signal=time_to_signal,
    )
    upside = inputs.impact * inputs.confidence * (1 + inputs.revenue_alignment / 10)
    cost = (1 + inputs.effort / 10) * (1 + inputs.time_to_signal / 10)
    safety = 0.5 + inputs.reversibility / 20
    return round(min(100.0, upside / cost * safety), 2)
