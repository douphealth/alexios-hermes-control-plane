from datetime import date

from alexios_hermes_control_plane.activities.evidence import (
    _delta,
    _evidence_id,
    _payload_hash,
    _totals,
)


def test_payload_hash_is_stable_for_key_order() -> None:
    assert _payload_hash({"b": 2, "a": 1}) == _payload_hash({"a": 1, "b": 2})


def test_evidence_id_is_deterministic() -> None:
    start = date(2026, 8, 1)
    end = date(2026, 8, 28)
    first = _evidence_id("gearuptofit", "top_pages", start, end, "abc")
    second = _evidence_id("gearuptofit", "top_pages", start, end, "abc")
    assert first == second
    assert first.startswith("gsc_")


def test_totals_uses_impression_weighted_position() -> None:
    result = _totals(
        [
            {"clicks": 10.0, "impressions": 100.0, "position": 2.0},
            {"clicks": 5.0, "impressions": 50.0, "position": 8.0},
        ]
    )
    assert result["clicks"] == 15.0
    assert result["impressions"] == 150.0
    assert result["ctr"] == 0.1
    assert result["position"] == 4.0


def test_delta_handles_zero_baseline() -> None:
    assert _delta(10.0, 0.0) is None
    assert _delta(120.0, 100.0) == 0.2
