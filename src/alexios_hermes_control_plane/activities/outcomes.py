import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

import asyncpg  # type: ignore[import-untyped]
import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.prompts.portfolio_context import load_portfolio_sites
from alexios_hermes_control_plane.schemas.execution import MutationReceipt, WordPressMutation

_GSC_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
_GSC_QUERY_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
_WINDOWS = (7, 14, 28)
_GSC_FINALITY_LAG_DAYS = 3


def _credentials_token(service_account_file: str) -> str:
    path = Path(service_account_file).expanduser()
    credentials = service_account.Credentials.from_service_account_file(  # type: ignore[no-untyped-call]
        str(path), scopes=[_GSC_SCOPE]
    )
    credentials.refresh(Request())
    if not credentials.token:
        raise RuntimeError("GSC token refresh returned no token")
    return str(credentials.token)


def _property_for_site(site_id: str) -> str:
    sites = load_portfolio_sites(get_settings().portfolio_sites_json)
    matches = [item for item in sites if str(item.get("site_id")) == site_id]
    if len(matches) != 1:
        raise ValueError(f"Expected one portfolio site for site_id={site_id}")
    property_id = str(matches[0].get("gsc_property") or "")
    if not property_id:
        raise ValueError(f"Missing GSC property for site_id={site_id}")
    return property_id


async def _url_metrics(
    client: httpx.AsyncClient,
    token: str,
    property_id: str,
    target_url: str,
    start: date,
    end: date,
) -> dict[str, float]:
    endpoint = f"{_GSC_QUERY_BASE}/{quote(property_id, safe='')}/searchAnalytics/query"
    response = await client.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["page"],
            "dimensionFilterGroups": [
                {"filters": [{"dimension": "page", "operator": "equals", "expression": target_url}]}
            ],
            "rowLimit": 10,
            "dataState": "final",
        },
    )
    response.raise_for_status()
    data = response.json()
    rows = data.get("rows", []) if isinstance(data, dict) else []
    if not isinstance(rows, list) or not rows:
        return {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    row = rows[0]
    if not isinstance(row, dict):
        return {"clicks": 0.0, "impressions": 0.0, "ctr": 0.0, "position": 0.0}
    return {
        "clicks": float(row.get("clicks", 0.0)),
        "impressions": float(row.get("impressions", 0.0)),
        "ctr": float(row.get("ctr", 0.0)),
        "position": float(row.get("position", 0.0)),
    }


@activity.defn
async def capture_gsc_baselines(site_id: str, target_url: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.gsc_service_account_file:
        return {}
    token = await asyncio.to_thread(_credentials_token, settings.gsc_service_account_file)
    property_id = _property_for_site(site_id)
    current_end = datetime.now(UTC).date() - timedelta(days=1)
    baselines: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=45.0) as client:
        for window in _WINDOWS:
            start = current_end - timedelta(days=window - 1)
            baselines[str(window)] = await _url_metrics(
                client, token, property_id, target_url, start, current_end
            )
    return baselines


@activity.defn
async def record_autonomous_mutation(
    workflow_id: str,
    mutation_payload: dict[str, Any],
    receipt_payload: dict[str, Any],
    baseline: dict[str, Any],
) -> None:
    settings = get_settings()
    mutation = WordPressMutation.model_validate(mutation_payload)
    receipt = MutationReceipt.model_validate(receipt_payload)
    connection = await asyncpg.connect(settings.database_url)
    try:
        await connection.execute(
            """
            INSERT INTO autonomous_mutations(
                mutation_id, workflow_id, site_id, target_url, post_id, mutation_type,
                status, evidence_ids, before_sha256, after_sha256, backup_path,
                baseline_json, rolled_back
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12::jsonb,$13)
            ON CONFLICT (mutation_id) DO UPDATE SET
                status=EXCLUDED.status,
                after_sha256=EXCLUDED.after_sha256,
                backup_path=EXCLUDED.backup_path,
                baseline_json=EXCLUDED.baseline_json,
                rolled_back=EXCLUDED.rolled_back
            """,
            mutation.mutation_id,
            workflow_id,
            mutation.site_id,
            mutation.target_url,
            mutation.post_id,
            mutation.mutation_type.value,
            receipt.status,
            json.dumps(mutation.evidence_ids),
            receipt.before_sha256,
            receipt.after_sha256,
            receipt.backup_path,
            json.dumps(baseline),
            receipt.rolled_back,
        )
    finally:
        await connection.close()


@activity.defn
async def list_due_measurements(limit: int = 50) -> list[dict[str, Any]]:
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        rows = await connection.fetch(
            """
            WITH windows(window_days) AS (VALUES (7), (14), (28))
            SELECT m.mutation_id, m.site_id, m.target_url, m.applied_at,
                   m.baseline_json, w.window_days
            FROM autonomous_mutations m
            CROSS JOIN windows w
            LEFT JOIN autonomous_measurements x
              ON x.mutation_id=m.mutation_id AND x.window_days=w.window_days
            WHERE m.status='VALIDATED'
              AND m.rolled_back=false
              AND x.id IS NULL
              AND m.applied_at <= now() - ((w.window_days + $1) * interval '1 day')
            ORDER BY m.applied_at ASC, w.window_days ASC
            LIMIT $2
            """,
            _GSC_FINALITY_LAG_DAYS,
            limit,
        )
        return [dict(row) for row in rows]
    finally:
        await connection.close()


def _metric_delta(current: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return round((current - baseline) / baseline, 6)


@activity.defn
async def measure_and_record_outcome(item: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    service_file = settings.gsc_service_account_file
    if not service_file:
        raise RuntimeError("GSC_SERVICE_ACCOUNT_FILE is required for outcome measurement")
    site_id = str(item["site_id"])
    target_url = str(item["target_url"])
    window_days = int(item["window_days"])
    applied_at = item["applied_at"]
    if not isinstance(applied_at, datetime):
        raise TypeError("applied_at must be a datetime")
    start = applied_at.astimezone(UTC).date() + timedelta(days=1)
    end = start + timedelta(days=window_days - 1)
    token = await asyncio.to_thread(_credentials_token, service_file)
    property_id = _property_for_site(site_id)
    async with httpx.AsyncClient(timeout=45.0) as client:
        metrics = await _url_metrics(client, token, property_id, target_url, start, end)

    raw_baseline = item.get("baseline_json") or {}
    if isinstance(raw_baseline, str):
        raw_baseline = json.loads(raw_baseline)
    baseline = raw_baseline.get(str(window_days), {}) if isinstance(raw_baseline, dict) else {}
    baseline = baseline if isinstance(baseline, dict) else {}
    baseline_metrics = {
        key: float(baseline.get(key, 0.0)) for key in ("clicks", "impressions", "ctr", "position")
    }
    delta = {
        "clicks_pct": _metric_delta(metrics["clicks"], baseline_metrics["clicks"]),
        "impressions_pct": _metric_delta(metrics["impressions"], baseline_metrics["impressions"]),
        "ctr_pct": _metric_delta(metrics["ctr"], baseline_metrics["ctr"]),
        "position_change": round(metrics["position"] - baseline_metrics["position"], 4),
    }

    connection = await asyncpg.connect(settings.database_url)
    try:
        await connection.execute(
            """
            INSERT INTO autonomous_measurements(
                mutation_id, window_days, period_start, period_end,
                clicks, impressions, ctr, position,
                baseline_clicks, baseline_impressions, baseline_ctr, baseline_position,
                delta_json
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)
            ON CONFLICT (mutation_id, window_days) DO NOTHING
            """,
            str(item["mutation_id"]),
            window_days,
            start,
            end,
            metrics["clicks"],
            metrics["impressions"],
            metrics["ctr"],
            metrics["position"],
            baseline_metrics["clicks"],
            baseline_metrics["impressions"],
            baseline_metrics["ctr"],
            baseline_metrics["position"],
            json.dumps(delta),
        )
    finally:
        await connection.close()
    return {
        "mutation_id": str(item["mutation_id"]),
        "site_id": site_id,
        "target_url": target_url,
        "window_days": window_days,
        "metrics": metrics,
        "baseline": baseline_metrics,
        "delta": delta,
    }


@activity.defn
async def recent_outcome_memory(limit: int = 30) -> list[dict[str, Any]]:
    settings = get_settings()
    connection = await asyncpg.connect(settings.database_url)
    try:
        rows = await connection.fetch(
            """
            SELECT m.site_id, m.target_url, m.mutation_type, x.window_days, x.delta_json
            FROM autonomous_measurements x
            JOIN autonomous_mutations m ON m.mutation_id=x.mutation_id
            ORDER BY x.measured_at DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]
    finally:
        await connection.close()
