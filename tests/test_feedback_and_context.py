import json

from alexios_hermes_control_plane.prompts.portfolio_context import (
    DEFAULT_PORTFOLIO_SITES,
    format_feedback_memory,
    format_operating_rules,
    format_recent_runs,
    format_sites,
    load_portfolio_sites,
)
from alexios_hermes_control_plane.services.telegram import parse_feedback_command


def test_default_portfolio_covers_nine_canonical_sites() -> None:
    assert len(DEFAULT_PORTFOLIO_SITES) == 9
    sites = load_portfolio_sites()
    names = {str(s["domain"]) for s in sites}
    assert {
        "affiliatemarketingforsuccess.com",
        "gearuptofit.com",
        "plantastichaven.com",
        "gearuptogrow.com",
        "mysticaldigits.com",
        "frenchyfab.com",
        "micegoneguide.com",
        "efficientgptprompts.com",
        "openclaw-skillshub.com",
    } == names
    assert len({s["site_id"] for s in sites}) == 9
    assert all(s["gsc_property"].startswith("sc-domain:") for s in sites)


def test_json_override_is_normalized() -> None:
    override = json.dumps([{"site": "newsite.example", "niche": "test"}])
    sites = load_portfolio_sites(override)
    assert sites[0]["domain"] == "newsite.example"
    assert sites[0]["site_id"] == "newsite-example"
    assert sites[0]["gsc_property"] == "sc-domain:newsite.example"


def test_invalid_json_override_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        load_portfolio_sites("{not json")


def test_format_sites_includes_notes() -> None:
    text = format_sites(
        [
            {
                "site": "affiliatemarketingforsuccess.com",
                "domain": "affiliatemarketingforsuccess.com",
                "site_id": "affiliate-marketing-for-success",
                "niche": "affiliate marketing",
                "note": "never tag contextual prose",
            }
        ]
    )
    assert "affiliatemarketingforsuccess.com" in text
    assert "affiliate-marketing-for-success" in text
    assert "never tag contextual prose" in text


def test_format_feedback_memory_empty_and_present() -> None:
    assert "No operator verdicts" in format_feedback_memory([])
    text = format_feedback_memory(
        [
            {
                "run_id": "portfolio-idem-abc",
                "intervention_rank": 1,
                "verdict": "REJECTED",
                "outcome_note": "too risky",
            }
        ]
    )
    assert "REJECTED" in text
    assert "too risky" in text


def test_format_recent_runs_empty_and_present() -> None:
    assert "first run" in format_recent_runs([]).lower()
    text = format_recent_runs(
        [{"run_id": "r1", "objective": "boost indexation", "intervention_titles": ["Fix sitemap"]}]
    )
    assert "boost indexation" in text
    assert "Fix sitemap" in text


def test_operating_rules_render_numbered() -> None:
    text = format_operating_rules()
    assert "1." in text
    assert "papalex-20" in text


def test_parse_feedback_command_valid() -> None:
    parsed = parse_feedback_command("/feedback a1b2 2 EXECUTED_VERIFIED ctr up 12%")
    assert parsed == ("a1b2", 2, "EXECUTED_VERIFIED ctr up 12%")


def test_parse_feedback_command_invalid() -> None:
    assert parse_feedback_command("/portfolio run it") is None
    assert parse_feedback_command("/feedback") is None
    assert parse_feedback_command("/feedback a1b2 two EXECUTED_VERIFIED") is None
    assert parse_feedback_command("/feedback a1b2 2 BOGUS") is None
    assert parse_feedback_command("/feedback a1b2 5 ADOPTED") is None
