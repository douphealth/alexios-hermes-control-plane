"""First-party evidence ingestion activities.

External reads happen in Temporal activities so workflow replay stays deterministic.
"""

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from temporalio import activity

from alexios_hermes_control_plane.config import Settings, get_settings
from alexios_hermes_control_plane.schemas.common import Evidence

_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_API = "https://searchconsole.googleapis.com/webmasters/v3"


def _canonical_hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evidence(
    *,
    site: dict[str, str],
    kind: str,
    source_property: str,
    period_start: date,
    period_end: date,
    summary: str,
    payload: dict[str, Any],
) -> Evidence:
    identity = {
        "source": "gsc",
        "site_id": site["site_id"],
        "kind": kind,
        "source_property": source_property,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "payload": payload,
    }
    return Evidence(
        evidence_id=f"gsc:{site['site_id']}:{kind}:{_canonical_hash(identity)[:20]}",
        source="gsc",
        site_id=site["site_id"],
        kind=kind,
        observed_at=datetime.now(UTC),
        period_start=period_start,
        period_end=period_end,
        source_property=source_property,
        payload_hash=_canonical_hash(payload),
        summary=summary,
        payload=payload,
    )


def _metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    clicks = sum(float(row.get("clicks", 0)) for row in rows)
    impressions = sum(float(row.get("impressions", 0)) for row in rows)
    weighted_position = sum(
        float(row.get("position", 0)) * float(row.get("impressions", 0)) for row in rows
    )
    return {
        "clicks": round(clicks, 3),
        "impressions": round(impressions, 3),
        "ctr": round(clicks / impressions, 6) if impressions else 0.0,
        "position": round(weighted_position / impressions, 3) if impressions else 0.0,
    }


def _aggregate_dimension(rows: list[dict[str, Any]], index: int) -> list[dict[str, Any]]:
    aggregate: dict[str, dict[str, float]] = defaultdict(
        lambda: {"clicks": 0.0, "impressions": 0.0, "weighted_position": 0.0}
    )
    for row in rows:
        keys = row.get("keys", [])
        if not isinstance(keys, list) or len(keys) <= index:
            continue
        key = str(keys[index])
        clicks = float(row.get("clicks", 0))
        impressions = float(row.get("impressions", 0))
        aggregate[key]["clicks"] += clicks
        aggregate[key]["impressions"] += impressions
        aggregate[key]["weighted_position"] += float(row.get("position", 0)) * impressions
    result: list[dict[str, Any]] = []
    for key, value in aggregate.items():
        impressions = value["impressions"]
        clicks = value["clicks"]
        result.append(
            {
                "key": key,
                "clicks": round(clicks, 3),
                "impressions": round(impressions, 3),
                "ctr": round(clicks / impressions, 6) if impressions else 0.0,
                "position": round(value["weighted_position"] / impressions, 3)
                if impressions
                else 0.0,
            }
        )
    return sorted(result, key=lambda item: (item["impressions"], item["clicks"]), reverse=True)


def _opportunities(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    pages = _aggregate_dimension(rows, 0)
    queries = _aggregate_dimension(rows, 1)
    return {
        "striking_distance_queries": [
            item
            for item in queries
            if item["impressions"] >= 10 and 4.0 <= item["position"] <= 20.0
        ][:50],
        "high_impression_low_ctr_queries": [
            item for item in queries if item["impressions"] >= 20 and item["ctr"] < 0.02
        ][:50],
        "top_pages": pages[:50],
        "top_queries": queries[:50],
    }


class GscClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.gsc_service_account_file:
            raise RuntimeError("GSC_SERVICE_ACCOUNT_FILE is not configured")
        path = Path(settings.gsc_service_account_file).expanduser()
        if not path.is_file():
            raise RuntimeError(f"GSC service-account file not found: {path}")
        self._credentials = service_account.Credentials.from_service_account_file(
            str(path), scopes=[_SCOPE]
        )
        self._timeout = settings.gsc_request_timeout_seconds
        self._row_limit = settings.gsc_row_limit

    async def _token(self) -> str:
        if not self._credentials.valid:
            await asyncio.to_thread(self._credentials.refresh, Request())
        token = self._credentials.token
        if not token:
            raise RuntimeError("GSC credential refresh returned no access token")
        return token

    async def _request(
        self, method: str, url: str, *, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        token = await self._token()
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("GSC returned a non-object response")
        return data

    async def properties(self) -> list[str]:
        data = await self._request("GET", f"{_API}/sites")
        entries = data.get("siteEntry", [])
        if not isinstance(entries, list):
            return []
        return [str(item.get("siteUrl")) for item in entries if isinstance(item, dict)]

    async def search_analytics(
        self, property_url: str, start_date: date, end_date: date
    ) -> list[dict[str, Any]]:
        encoded = quote(property_url, safe="")
        data = await self._request(
            "POST",
            f"{_API}/sites/{encoded}/searchAnalytics/query",
            body={
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": ["page", "query"],
                "rowLimit": self._row_limit,
                "dataState": "final",
            },
        )
        rows = data.get("rows", [])
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _resolve_property(site: dict[str, str], available: list[str]) -> str | None:
    configured = site.get("gsc_property", "")
    if configured and configured in available:
        return configured
    domain = site.get("domain", "").lower().strip()
    domain_property = f"sc-domain:{domain}"
    if domain_property in available:
        return domain_property
    prefixes = [
        candidate
        for candidate in available
        if candidate.startswith("http") and domain and domain in candidate.lower()
    ]
    return sorted(prefixes, key=len)[0] if prefixes else None


async def _collect_site(
    client: GscClient,
    site: dict[str, str],
    available: list[str],
    settings: Settings,
) -> tuple[list[Evidence], str | None]:
    property_url = _resolve_property(site, available)
    if not property_url:
        return [], f"{site['domain']}: no authorized GSC property matched"
    current_end = date.today() - timedelta(days=settings.gsc_data_lag_days)
    current_start = current_end - timedelta(days=settings.gsc_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=settings.gsc_days - 1)
    try:
        current_rows, previous_rows = await asyncio.gather(
            client.search_analytics(property_url, current_start, current_end),
            client.search_analytics(property_url, previous_start, previous_end),
        )
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return [], f"{site['domain']}: {type(exc).__name__}: {str(exc)[:300]}"

    current = _metrics(current_rows)
    previous = _metrics(previous_rows)
    comparison = {
        "current": current,
        "previous": previous,
        "delta": {
            "clicks": round(current["clicks"] - previous["clicks"], 3),
            "impressions": round(current["impressions"] - previous["impressions"], 3),
            "ctr": round(current["ctr"] - previous["ctr"], 6),
            "position": round(current["position"] - previous["position"], 3),
        },
        "row_count_current": len(current_rows),
        "row_count_previous": len(previous_rows),
    }
    summary = _evidence(
        site=site,
        kind="performance_summary",
        source_property=property_url,
        period_start=current_start,
        period_end=current_end,
        summary=(
            f"{site['domain']} GSC {settings.gsc_days}d: {current['clicks']:.0f} clicks, "
            f"{current['impressions']:.0f} impressions, CTR {current['ctr']:.2%}, "
            f"avg position {current['position']:.1f}; compared with previous period."
        ),
        payload=comparison,
    )
    opportunity_payload = _opportunities(current_rows)
    opportunities = _evidence(
        site=site,
        kind="search_opportunities",
        source_property=property_url,
        period_start=current_start,
        period_end=current_end,
        summary=(
            f"{site['domain']} GSC opportunity set: "
            f"{len(opportunity_payload['striking_distance_queries'])} striking-distance queries, "
            f"{len(opportunity_payload['high_impression_low_ctr_queries'])} high-impression low-CTR queries."
        ),
        payload=opportunity_payload,
    )
    return [summary, opportunities], None


@activity.defn
async def collect_gsc_evidence(sites: list[dict[str, str]]) -> dict[str, object]:
    """Collect isolated, typed GSC snapshots for the requested canonical sites."""
    settings = get_settings()
    if not settings.gsc_enabled:
        return {
            "evidence": [],
            "note": "GSC evidence disabled: GSC_SERVICE_ACCOUNT_FILE is not configured.",
            "errors": [],
        }
    try:
        client = GscClient(settings)
        available = await client.properties()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return {
            "evidence": [],
            "note": "GSC evidence unavailable; agents must treat GSC-dependent claims as NEEDS_DATA.",
            "errors": [f"{type(exc).__name__}: {str(exc)[:500]}"],
        }

    results = await asyncio.gather(
        *[_collect_site(client, site, available, settings) for site in sites]
    )
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    for items, error in results:
        evidence.extend(item.model_dump(mode="json") for item in items)
        if error:
            errors.append(error)
    note = (
        f"Live GSC evidence loaded: {len(evidence)} snapshots across "
        f"{len(evidence) // 2} matched site(s)."
    )
    if errors:
        note += f" {len(errors)} site/property error(s) were isolated; do not infer missing data."
    return {"evidence": evidence, "note": note, "errors": errors}
