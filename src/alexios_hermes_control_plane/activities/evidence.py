"""First-party evidence collection activities.

All network and credential reads live in activities so Temporal workflow replay remains
deterministic. GSC evidence is read-only and normalized into stable Evidence records.
"""

import asyncio
import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.schemas.common import Evidence

_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_GSC_QUERY_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()


def _evidence_id(site_id: str, kind: str, start: date, end: date, payload_hash: str) -> str:
    seed = f"gsc|{site_id}|{kind}|{start.isoformat()}|{end.isoformat()}|{payload_hash}"
    return "gsc_" + hashlib.sha256(seed.encode()).hexdigest()[:24]


def _credentials_token(service_account_file: str) -> str:
    path = Path(service_account_file).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"GSC service-account file not found: {path}")
    credentials = service_account.Credentials.from_service_account_file(
        str(path), scopes=[_GSC_SCOPE]
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("GSC service-account token refresh returned no token")
    return credentials.token


async def _query_search_analytics(
    client: httpx.AsyncClient,
    token: str,
    property_id: str,
    start: date,
    end: date,
    dimensions: list[str],
    row_limit: int,
) -> dict[str, Any]:
    url = f"{_GSC_QUERY_BASE}/{quote(property_id, safe='')}/searchAnalytics/query"
    response = await client.post(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": dimensions,
            "rowLimit": row_limit,
            "dataState": "final",
        },
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise TypeError("GSC Search Analytics response was not an object")
    return data


def _totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    clicks = sum(float(row.get("clicks", 0.0)) for row in rows)
    impressions = sum(float(row.get("impressions", 0.0)) for row in rows)
    weighted_position = sum(
        float(row.get("position", 0.0)) * float(row.get("impressions", 0.0)) for row in rows
    )
    return {
        "clicks": round(clicks, 4),
        "impressions": round(impressions, 4),
        "ctr": round(clicks / impressions, 6) if impressions else 0.0,
        "position": round(weighted_position / impressions, 4) if impressions else 0.0,
    }


def _delta(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return round((current - previous) / previous, 6)


def _normalize_rows(rows: object, key_name: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        keys = row.get("keys", [])
        key = str(keys[0]) if isinstance(keys, list) and keys else ""
        normalized.append(
            {
                key_name: key,
                "clicks": float(row.get("clicks", 0.0)),
                "impressions": float(row.get("impressions", 0.0)),
                "ctr": float(row.get("ctr", 0.0)),
                "position": float(row.get("position", 0.0)),
            }
        )
    return normalized


def _make_evidence(
    *,
    site_id: str,
    kind: str,
    property_id: str,
    start: date,
    end: date,
    summary: str,
    payload: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    digest = _payload_hash(payload)
    evidence = Evidence(
        evidence_id=_evidence_id(site_id, kind, start, end, digest),
        source="google_search_console",
        summary=summary,
        site_id=site_id,
        kind=kind,
        observed_at=observed_at,
        period_start=start.isoformat(),
        period_end=end.isoformat(),
        source_property=property_id,
        payload_hash=digest,
        payload=payload,
    )
    return evidence.model_dump(mode="json")


@activity.defn
async def collect_gsc_evidence(sites: list[dict[str, str]]) -> dict[str, object]:
    settings = get_settings()
    if not settings.gsc_service_account_file:
        return {
            "evidence": [],
            "note": "GSC connector disabled: GSC_SERVICE_ACCOUNT_FILE is not configured.",
            "errors": [],
        }

    token = await asyncio.to_thread(_credentials_token, settings.gsc_service_account_file)
    today = datetime.now(UTC).date()
    current_end = today - timedelta(days=1)
    current_start = current_end - timedelta(days=settings.gsc_lookback_days - 1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=settings.gsc_lookback_days - 1)
    observed_at = datetime.now(UTC).isoformat()

    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    selected_sites = sites[: settings.gsc_max_sites_per_run]

    async with httpx.AsyncClient(timeout=45.0) as client:
        for site in selected_sites:
            site_id = str(site.get("site_id") or site.get("site") or "unknown")
            property_id = str(site.get("gsc_property") or "")
            if not property_id:
                errors.append(f"{site_id}: missing gsc_property")
                continue
            try:
                current_pages, previous_pages, current_queries = await asyncio.gather(
                    _query_search_analytics(
                        client,
                        token,
                        property_id,
                        current_start,
                        current_end,
                        ["page"],
                        settings.gsc_row_limit,
                    ),
                    _query_search_analytics(
                        client,
                        token,
                        property_id,
                        previous_start,
                        previous_end,
                        ["page"],
                        settings.gsc_row_limit,
                    ),
                    _query_search_analytics(
                        client,
                        token,
                        property_id,
                        current_start,
                        current_end,
                        ["query"],
                        settings.gsc_row_limit,
                    ),
                )
            except (httpx.HTTPError, TypeError, ValueError) as exc:
                errors.append(f"{site_id}: {type(exc).__name__}: {str(exc)[:240]}")
                continue

            current_page_rows = _normalize_rows(current_pages.get("rows", []), "page")
            previous_page_rows = _normalize_rows(previous_pages.get("rows", []), "page")
            query_rows = _normalize_rows(current_queries.get("rows", []), "query")
            current_totals = _totals(current_page_rows)
            previous_totals = _totals(previous_page_rows)

            summary_payload = {
                "current": current_totals,
                "previous": previous_totals,
                "delta": {
                    "clicks_pct": _delta(current_totals["clicks"], previous_totals["clicks"]),
                    "impressions_pct": _delta(
                        current_totals["impressions"], previous_totals["impressions"]
                    ),
                    "ctr_pct": _delta(current_totals["ctr"], previous_totals["ctr"]),
                    "position_change": round(
                        current_totals["position"] - previous_totals["position"], 4
                    ),
                },
            }
            evidence.append(
                _make_evidence(
                    site_id=site_id,
                    kind="search_performance_summary",
                    property_id=property_id,
                    start=current_start,
                    end=current_end,
                    summary=(
                        f"GSC {settings.gsc_lookback_days}-day performance for {site_id}: "
                        f"{current_totals['clicks']:.0f} clicks, "
                        f"{current_totals['impressions']:.0f} impressions, "
                        f"CTR {current_totals['ctr']:.2%}, "
                        f"avg position {current_totals['position']:.2f}."
                    ),
                    payload=summary_payload,
                    observed_at=observed_at,
                )
            )

            pages_payload = {"rows": current_page_rows}
            evidence.append(
                _make_evidence(
                    site_id=site_id,
                    kind="top_pages",
                    property_id=property_id,
                    start=current_start,
                    end=current_end,
                    summary=f"Top GSC pages for {site_id} over the current comparison window.",
                    payload=pages_payload,
                    observed_at=observed_at,
                )
            )

            queries_payload = {"rows": query_rows}
            evidence.append(
                _make_evidence(
                    site_id=site_id,
                    kind="top_queries",
                    property_id=property_id,
                    start=current_start,
                    end=current_end,
                    summary=f"Top GSC queries for {site_id} over the current comparison window.",
                    payload=queries_payload,
                    observed_at=observed_at,
                )
            )

    note = (
        f"GSC evidence collected for {len(selected_sites)} configured sites; "
        f"{len(evidence)} evidence records produced."
    )
    if errors:
        note += f" {len(errors)} site-level connector errors were isolated."
    return {"evidence": evidence, "note": note, "errors": errors}
