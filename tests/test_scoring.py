import pytest
from pydantic import ValidationError

from alexios_hermes_control_plane.services.scoring import decision_score


def test_score_is_deterministic_and_bounded() -> None:
    kwargs = dict(
        impact=8,
        confidence=0.8,
        revenue_alignment=7,
        effort=3,
        reversibility=9,
        time_to_signal=4,
    )
    first = decision_score(**kwargs)
    second = decision_score(**kwargs)
    assert first == second
    assert 0 <= first <= 100


def test_high_impact_low_effort_outranks_low_impact_high_effort() -> None:
    strong = decision_score(
        impact=9, confidence=0.9, revenue_alignment=9, effort=2, reversibility=8, time_to_signal=2
    )
    weak = decision_score(
        impact=3, confidence=0.5, revenue_alignment=3, effort=9, reversibility=4, time_to_signal=9
    )
    assert strong > weak * 3


def test_reversibility_rewards_safe_interventions() -> None:
    base = dict(impact=7, confidence=0.7, revenue_alignment=6, effort=4, time_to_signal=4)
    safe = decision_score(reversibility=10, **base)
    risky = decision_score(reversibility=0, **base)
    assert safe > risky


def test_zero_confidence_kills_upside() -> None:
    assert (
        decision_score(
            impact=10, confidence=0, revenue_alignment=10,
            effort=1, reversibility=10, time_to_signal=1,
        )
        == 0
    )


def test_invalid_inputs_rejected() -> None:
    with pytest.raises(ValidationError):
        decision_score(
            impact=11, confidence=0.5, revenue_alignment=5,
            effort=5, reversibility=5, time_to_signal=5,
        )
    with pytest.raises(ValidationError):
        decision_score(
            impact=5, confidence=1.5, revenue_alignment=5,
            effort=5, reversibility=5, time_to_signal=5,
        )
