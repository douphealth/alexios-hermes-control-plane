from alexios_hermes_control_plane.activities.agents import _compact_context_for_role


def _context() -> dict[str, object]:
    return {
        "sites": [{"site": "example.com"}],
        "sites_display": "duplicate display text",
        "operating_rules": ["read only"],
        "operating_rules_display": "duplicate rules",
        "recent_runs": [],
        "recent_runs_display": "duplicate recent runs",
        "feedback_memory": [],
        "feedback_memory_display": "duplicate feedback",
        "evidence": [
            {
                "evidence_id": "e1",
                "site_id": "example.com",
                "kind": "top_pages",
                "summary": "Top pages",
                "payload": {"rows": [{"page": f"/{i}"} for i in range(50)]},
            }
        ],
    }


def test_specialist_context_bounds_large_evidence_rows() -> None:
    compact = _compact_context_for_role("diagnostician", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    payload = evidence[0]["payload"]
    assert len(payload["rows"]) == 30
    assert payload["rows_truncated"] == 20
    assert "sites_display" not in compact


def test_chief_of_staff_uses_evidence_summaries_only() -> None:
    compact = _compact_context_for_role("chief_of_staff", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    assert evidence[0]["evidence_id"] == "e1"
    assert "payload" not in evidence[0]
