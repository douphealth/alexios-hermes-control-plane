from alexios_hermes_control_plane.activities.agents import _compact_context_for_role


def _context() -> dict[str, object]:
    return {
        "sites": [{"site": "example.com"}],
        "sites_display": "duplicate display text",
        "operating_rules": ["read only"],
        "operating_rules_display": "duplicate rules",
        "recent_runs": [{"run_id": f"r{i}"} for i in range(8)],
        "recent_runs_display": "duplicate recent runs",
        "feedback_memory": [{"run_id": f"f{i}"} for i in range(15)],
        "feedback_memory_display": "duplicate feedback",
        "evidence": [
            {
                "evidence_id": "e-pages",
                "site_id": "example.com",
                "kind": "top_pages",
                "summary": "Top pages",
                "payload_hash": "hash-pages",
                "payload": {"rows": [{"page": f"/{i}"} for i in range(50)]},
            },
            {
                "evidence_id": "e-queries",
                "site_id": "example.com",
                "kind": "top_queries",
                "summary": "Top queries",
                "payload_hash": "hash-queries",
                "payload": {"rows": [{"query": f"q{i}"} for i in range(50)]},
            },
        ],
    }


def test_diagnostician_context_is_small_and_page_focused() -> None:
    compact = _compact_context_for_role("diagnostician", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) == 1
    assert evidence[0]["kind"] == "top_pages"
    payload = evidence[0]["payload"]
    assert len(payload["rows"]) == 10
    assert payload["rows_truncated"] == 40
    assert "recent_runs" not in compact
    assert "feedback_memory" not in compact
    assert "sites_display" not in compact


def test_strategist_keeps_bounded_queries_and_small_history() -> None:
    compact = _compact_context_for_role("strategist", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    assert len(evidence) == 2
    assert all(len(item["payload"]["rows"]) == 12 for item in evidence)
    assert len(compact["recent_runs"]) == 3
    assert "feedback_memory" not in compact


def test_chief_of_staff_uses_summaries_and_bounded_memory() -> None:
    compact = _compact_context_for_role("chief_of_staff", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    assert evidence[0]["evidence_id"] == "e-pages"
    assert evidence[0]["payload_hash"] == "hash-pages"
    assert "payload" not in evidence[0]
    assert len(compact["recent_runs"]) == 5
    assert len(compact["feedback_memory"]) == 10


def test_judge_uses_evidence_summaries_without_history() -> None:
    compact = _compact_context_for_role("judge", _context())
    evidence = compact["evidence"]
    assert isinstance(evidence, list)
    assert all("payload" not in item for item in evidence)
    assert "recent_runs" not in compact
    assert "feedback_memory" not in compact
