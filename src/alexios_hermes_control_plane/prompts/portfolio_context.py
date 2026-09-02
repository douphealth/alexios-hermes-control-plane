"""Portfolio context: canonical entities and operating rules for agent reasoning."""

import json
from typing import Any

DEFAULT_PORTFOLIO_SITES: list[dict[str, str]] = [
    {
        "site_id": "affiliate-marketing-for-success",
        "site": "affiliatemarketingforsuccess.com",
        "domain": "affiliatemarketingforsuccess.com",
        "gsc_property": "sc-domain:affiliatemarketingforsuccess.com",
        "niche": "affiliate marketing education",
        "note": "AMFS: contextual Amazon prose is never tag-injected",
    },
    {
        "site_id": "gear-up-to-fit",
        "site": "gearuptofit.com",
        "domain": "gearuptofit.com",
        "gsc_property": "sc-domain:gearuptofit.com",
        "niche": "fitness, running, wearables and nutrition",
        "note": "indexation recovery and historically valuable URL preservation are P0",
    },
    {
        "site_id": "plantastic-haven",
        "site": "plantastichaven.com",
        "domain": "plantastichaven.com",
        "gsc_property": "sc-domain:plantastichaven.com",
        "niche": "houseplants and plant care",
        "note": "static robots; IndexNow active",
    },
    {
        "site_id": "gear-up-to-grow",
        "site": "gearuptogrow.com",
        "domain": "gearuptogrow.com",
        "gsc_property": "sc-domain:gearuptogrow.com",
        "niche": "personal development and growth",
        "note": "snippet layers can override metadata",
    },
    {
        "site_id": "mystical-digits",
        "site": "mysticaldigits.com",
        "domain": "mysticaldigits.com",
        "gsc_property": "sc-domain:mysticaldigits.com",
        "niche": "numerology",
        "note": "",
    },
    {
        "site_id": "frenchy-fab",
        "site": "frenchyfab.com",
        "domain": "frenchyfab.com",
        "gsc_property": "sc-domain:frenchyfab.com",
        "niche": "French bulldogs",
        "note": "",
    },
    {
        "site_id": "mice-gone-guide",
        "site": "micegoneguide.com",
        "domain": "micegoneguide.com",
        "gsc_property": "sc-domain:micegoneguide.com",
        "niche": "mouse and pest control",
        "note": "",
    },
    {
        "site_id": "efficient-gpt-prompts",
        "site": "efficientgptprompts.com",
        "domain": "efficientgptprompts.com",
        "gsc_property": "sc-domain:efficientgptprompts.com",
        "niche": "AI prompts and prompt engineering",
        "note": "code snippets execute in REST context only",
    },
    {
        "site_id": "openclaw-skills-hub",
        "site": "openclaw-skillshub.com",
        "domain": "openclaw-skillshub.com",
        "gsc_property": "sc-domain:openclaw-skillshub.com",
        "niche": "OpenClaw skills and AI agent tooling",
        "note": "crawlability and sitemap state are high priority",
    },
]

OPERATING_RULES: tuple[str, ...] = (
    "Affiliate tag for every site is papalex-20; WordPress stores & as both &#038; "
    "and &amp; — decode before any link or tag check.",
    "Purge LiteSpeed server cache BEFORE Cloudflare cache; on plantastichaven.com "
    "use CF purge_everything (LiteSpeed REST purge is 404).",
    "Never break design, analytics, commerce links, or security. Reversible changes "
    "only unless evidence demands otherwise.",
    "AMFS is the affiliate-marketing education site: bare Amazon prose there is contextual "
    "and must never be tag-injected.",
    "Snippet layers can override titles, descriptions, and schema — sync every layer plus "
    "Yoast indexables when changing metadata.",
    "Cloudflare caches 404s; a vanished page may still serve. Verify live state, not just origin.",
)


def _normalize_site(entry: dict[str, Any]) -> dict[str, str]:
    normalized = {str(k): str(v) for k, v in entry.items() if v is not None}
    domain = normalized.get("domain") or normalized.get("site", "")
    normalized.setdefault("domain", domain)
    normalized.setdefault("site", domain)
    normalized.setdefault("site_id", domain.replace(".", "-").replace("_", "-").strip("-"))
    normalized.setdefault("gsc_property", f"sc-domain:{domain}" if domain else "")
    normalized.setdefault("niche", "")
    normalized.setdefault("note", "")
    return normalized


def load_portfolio_sites(sites_json: str | None = None) -> list[dict[str, str]]:
    """Return canonical site entities; PORTFOLIO_SITES_JSON may override defaults."""
    if sites_json:
        try:
            parsed = json.loads(sites_json)
        except json.JSONDecodeError as exc:
            raise ValueError("PORTFOLIO_SITES_JSON is not valid JSON") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
            raise ValueError("PORTFOLIO_SITES_JSON must be a JSON list of objects")
        sites = [_normalize_site(item) for item in parsed]
    else:
        sites = [_normalize_site(item) for item in DEFAULT_PORTFOLIO_SITES]
    ids = [site["site_id"] for site in sites]
    domains = [site["domain"] for site in sites]
    if len(ids) != len(set(ids)) or len(domains) != len(set(domains)):
        raise ValueError("Portfolio site_id and domain values must be unique")
    return sites


def format_sites(sites: list[dict[str, str]]) -> str:
    lines = []
    for entry in sites:
        parts = [str(entry.get("domain") or entry.get("site", "?"))]
        if entry.get("site_id"):
            parts.append(f"id: {entry['site_id']}")
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
