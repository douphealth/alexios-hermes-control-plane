"""Portfolio context: the real-world ground the agents reason over.

Sites and operating rules are data, not prose, so they can be overridden by env
(PORTFOLIO_SITES_JSON) without code changes and injected into every agent context.
"""

import json
from typing import Any

DEFAULT_PORTFOLIO_SITES: list[dict[str, str]] = [
    {
        "site_id": "gearuptofit",
        "site": "gearuptofit.com",
        "niche": "fitness, running, wearables and nutrition",
        "gsc_property": "sc-domain:gearuptofit.com",
        "note": "prioritize indexation recovery and historically valuable URLs",
    },
    {
        "site_id": "affiliatemarketingforsuccess",
        "site": "affiliatemarketingforsuccess.com",
        "niche": "affiliate marketing, SEO and AI search visibility",
        "gsc_property": "sc-domain:affiliatemarketingforsuccess.com",
        "note": "bare Amazon prose is contextual; never auto-tag prose mentions",
    },
    {
        "site_id": "plantastichaven",
        "site": "plantastichaven.com",
        "niche": "houseplants and plant care",
        "gsc_property": "sc-domain:plantastichaven.com",
        "note": "static robots; IndexNow active",
    },
    {
        "site_id": "gearuptogrow",
        "site": "gearuptogrow.com",
        "niche": "personal development and growth",
        "gsc_property": "sc-domain:gearuptogrow.com",
        "note": "snippet layers may override titles, descriptions and schema",
    },
    {
        "site_id": "mysticaldigits",
        "site": "mysticaldigits.com",
        "niche": "numerology",
        "gsc_property": "sc-domain:mysticaldigits.com",
        "note": "",
    },
    {
        "site_id": "frenchyfab",
        "site": "frenchyfab.com",
        "niche": "French bulldogs",
        "gsc_property": "sc-domain:frenchyfab.com",
        "note": "preserve trust and commercial-page UX when monetizing",
    },
    {
        "site_id": "micegoneguide",
        "site": "micegoneguide.com",
        "niche": "mouse and pest control",
        "gsc_property": "sc-domain:micegoneguide.com",
        "note": "",
    },
    {
        "site_id": "efficientgptprompts",
        "site": "efficientgptprompts.com",
        "niche": "AI prompts and prompt engineering",
        "gsc_property": "sc-domain:efficientgptprompts.com",
        "note": "code snippets execute in REST context only",
    },
    {
        "site_id": "openclaw-skillshub",
        "site": "openclaw-skillshub.com",
        "niche": "OpenClaw skills and AI-agent tooling",
        "gsc_property": "sc-domain:openclaw-skillshub.com",
        "note": "prioritize crawlability and sitemap integrity before expansion",
    },
]

OPERATING_RULES: tuple[str, ...] = (
    "Affiliate tag for every site is papalex-20; WordPress stores & as both &#038; "
    "and &amp; — decode before any link or tag check.",
    "Purge LiteSpeed server cache BEFORE Cloudflare cache; on plantastichaven.com "
    "use CF purge_everything (LiteSpeed REST purge is 404).",
    "Never break design, analytics, commerce links, or security. Reversible changes "
    "only unless evidence demands otherwise.",
    "On affiliatemarketingforsuccess.com, bare Amazon prose is contextual and must "
    "never be tag-injected.",
    "Snippet layers can override titles, descriptions, and schema — sync every "
    "layer plus Yoast indexables when changing metadata.",
    "Cloudflare caches 404s; a vanished page may still serve. Verify live state, "
    "not just origin.",
)


def load_portfolio_sites(sites_json: str | None = None) -> list[dict[str, str]]:
    """Return the site registry; PORTFOLIO_SITES_JSON overrides the default."""
    if sites_json:
        try:
            parsed = json.loads(sites_json)
        except json.JSONDecodeError as exc:
            raise ValueError("PORTFOLIO_SITES_JSON is not valid JSON") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
            raise ValueError("PORTFOLIO_SITES_JSON must be a JSON list of objects")
        return parsed
    return DEFAULT_PORTFOLIO_SITES


def format_sites(sites: list[dict[str, str]]) -> str:
    lines = []
    for entry in sites:
        parts = [str(entry.get("site", "?"))]
        if entry.get("site_id"):
            parts.append(f"site_id: {entry['site_id']}")
        if entry.get("niche"):
            parts.append(f"niche: {entry['niche']}")
        if entry.get("gsc_property"):
            parts.append(f"gsc: {entry['gsc_property']}")
        if entry.get("note"):
            parts.append(f"note: {entry['note']}")
        lines.append(" - " + "; ".join(parts))
    return "\n".join(lines) if lines else " - (no sites registered)"


def format_operating_rules(rules: tuple[str, ...] = OPERATING_RULES) -> str:
    return "\n".join(f" {i}. {rule}" for i, rule in enumerate(rules, start=1))


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_recent_runs(recent_runs: list[dict[str, Any]]) -> str:
    if not recent_runs:
        return "No recorded completed runs. This may be the first run."
    lines = []
    for run in recent_runs:
        titles = "; ".join(str(t) for t in run.get("intervention_titles", [])[:3])
        lines.append(
            f"- run {run.get('run_id', '?')}: "
            f"objective='{_truncate(str(run.get('objective', '')), 160)}' "
            f"-> {titles or 'no interventions'}"
        )
    return "\n".join(lines)


def format_feedback_memory(feedback: list[dict[str, Any]]) -> str:
    if not feedback:
        return "No operator verdicts recorded yet."
    lines = []
    for item in feedback:
        raw_note = str(item.get("outcome_note") or "")
        note = f" — {_truncate(raw_note, 200)}" if raw_note else ""
        lines.append(
            f"- run {str(item.get('run_id', '?'))[:16]} "
            f"rank {item.get('intervention_rank', '?')}: "
            f"{item.get('verdict', '?')}{note}"
        )
    return "\n".join(lines)
