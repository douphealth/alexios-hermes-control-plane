from alexios_hermes_control_plane.activities.evidence import (
    _aggregate_dimension,
    _metrics,
    _opportunities,
    _resolve_property,
)
from alexios_hermes_control_plane.services.grounding import (
    eligible_finding_count,
    filter_grounded_payloads,
)


def _finding(
    finding_id: str,
    verification: str,
    evidence_ids: list[str],
    confidence: float = 0.9,
) -> dict[str, object]:
    return {
        "finding_id": finding_id,
        "category": "seo",
        "title": finding_id,
        "summary": "summary",
        "impact": 8,
        "confidence": confidence,
        "evidence_ids": evidence_ids,
        "recommended_action": "act",
        "verification": verification,
    }


def test_grounding_gate_removes_unverified_and_unknown_evidence() -> None:
    payloads = [
        {
            "findings": [
                _finding("grounded", "GROUNDED", ["e1"]),
                _finding("unknown-id", "GROUNDED", ["missing"]),
                _finding("unverified", "UNVERIFIED", ["e1"]),
                _finding("ungrounded", "UNGROUNDED", ["e1"]),
                _finding("empty", "GROUNDED", []),
            ]
        }
    ]
    safe = filter_grounded_payloads(payloads, {"e1"})
    assert [item["finding_id"] for item in safe[0]["findings"]] == ["grounded"]
    assert safe[0]["evidence_ids"] == ["e1"]
    assert eligible_finding_count(safe) == 1


def test_partial_finding_gets_deterministic_confidence_penalty() -> None:
    payloads = [{"findings": [_finding("partial", "PARTIAL", ["e1"], confidence=0.8)]}]
    safe = filter_grounded_payloads(payloads, {"e1"})
    assert safe[0]["findings"][0]["confidence"] == 0.48


def test_resolve_property_prefers_configured_domain_property() -> None:
    site = {
        "site_id": "gear-up-to-fit",
        "domain": "gearuptofit.com",
        "gsc_property": "sc-domain:gearuptofit.com",
    }
    available = ["https://www.gearuptofit.com/", "sc-domain:gearuptofit.com"]
    assert _resolve_property(site, available) == "sc-domain:gearuptofit.com"


def test_gsc_aggregation_and_opportunity_detection() -> None:
    rows = [
        {
            "keys": ["https://example.com/a", "best running shoes"],
            "clicks": 1,
            "impressions": 100,
            "ctr": 0.01,
            "position": 8,
        },
        {
            "keys": ["https://example.com/a", "running shoes"],
            "clicks": 10,
            "impressions": 100,
            "ctr": 0.1,
            "position": 3,
        },
    ]
    metrics = _metrics(rows)
    assert metrics["clicks"] == 11
    assert metrics["impressions"] == 200
    assert metrics["position"] == 5.5
    pages = _aggregate_dimension(rows, 0)
    assert pages[0]["key"] == "https://example.com/a"
    opportunities = _opportunities(rows)
    assert opportunities["striking_distance_queries"][0]["key"] == "best running shoes"
    assert opportunities["high_impression_low_ctr_queries"][0]["key"] == "best running shoes"
