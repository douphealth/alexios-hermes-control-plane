import pytest
from pydantic import ValidationError

from alexios_hermes_control_plane.schemas.common import (
    Finding,
    Intervention,
    JudgeOutput,
    PortfolioRunRequest,
    RunMode,
)


def test_portfolio_request_defaults_read_only() -> None:
    request = PortfolioRunRequest(objective="audit")
    assert request.mode is RunMode.READ_ONLY


def test_finding_rejects_invalid_confidence() -> None:
    with pytest.raises(ValidationError):
        Finding(
            finding_id="f1",
            category="technical",
            title="bad",
            summary="bad",
            impact=10,
            confidence=1.1,
            recommended_action="none",
        )


def _intervention(rank: int) -> Intervention:
    return Intervention(
        rank=rank,
        title=f"item-{rank}",
        target="https://example.com/",
        action="inspect",
        impact=9,
        confidence=0.9,
        revenue_alignment=8,
        effort=3,
        risk="LOW",
        reversibility=10,
        time_to_signal=7,
        expected_signal="better verified state",
    )


def test_judge_requires_contiguous_unique_ranks() -> None:
    with pytest.raises(ValidationError):
        JudgeOutput(interventions=[_intervention(1), _intervention(3)])
    with pytest.raises(ValidationError):
        JudgeOutput(interventions=[_intervention(1), _intervention(1)])
