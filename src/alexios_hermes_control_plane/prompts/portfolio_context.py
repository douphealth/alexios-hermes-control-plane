"""Portfolio context: the real-world ground the agents reason over.

Sites and operating rules are data, not prose, so they can be overridden by env
(PORTFOLIO_SITES_JSON) without code changes and injected into every agent context.
"""

import json
from typing import Any

DEFAULT_PORTFOLIO_SITES: list[dict[str, str]] = [
    {
        "site": "amfs-teaching",
        "niche": "teaching resources",
        "note": "bare Amazon prose is contextual, never tag links",
    },
    {"site": "mysticaldigits", "niche": "spirituality/numerology", "note": ""},
    {"site": "frenchyfab.com", "niche": "lifestyle", "note": "CTA box on 5 commercial slugs"},
    {"site": "micegoneguide.com", "niche": "pest control", "note": ""},
    {
        "site": "gearuptogrow.com",
        "niche": "gardening/growing",
        "note": "FAQ schema and title overrides are snippet-managed",
    },
    {"site": "plantastichaven.com", "niche": "plants", "note": "static robots, IndexNow active"},
    {
        "site": "efficientgptprompts.com",
        "niche": "AI prompts",
        "note": "code snippets execute in REST context only",
    },
    {"site": "gearuptofit", "niche": "fitness", "note": ""},
]

OPERATING_RULES: tuple[str, ...] = (
    "Affiliate tag for every site is papalex-20; WordPress stores & as both &#038; "
    "and &amp; — decode before any link or tag check.",
    "Purge LiteSpeed server cache BEFORE Cloudflare cache; on plantastichaven.com "
    "use CF purge_everything (LiteSpeed REST purge is 404).",
    "Never break design, analytics, commerce links, or security. Reversible changes "
    "only unless evidence demands otherwise.",
    "AMFS is the teaching site: bare Amazon prose there is contextual and must "
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
        if entry.get("niche"):
            parts.append(f"niche: {entry['niche']}")
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
