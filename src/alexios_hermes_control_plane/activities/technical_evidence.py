import hashlib
from datetime import UTC, datetime
from typing import Any

import httpx
from temporalio import activity

from alexios_hermes_control_plane.schemas.common import Evidence


def _evidence_id(site_id: str, payload: str) -> str:
    return "tech_" + hashlib.sha256(f"{site_id}|{payload}".encode()).hexdigest()[:24]


async def _probe(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        response = await client.get(url, follow_redirects=True)
        content_type = response.headers.get("content-type", "")[:120]
        text = response.text[:120000] if "text" in content_type or "xml" in content_type else ""
        return {
            "url": url,
            "final_url": str(response.url),
            "status": response.status_code,
            "content_type": content_type,
            "bytes": len(response.content),
            "has_noindex": "noindex" in text.lower(),
            "has_canonical": 'rel="canonical"' in text.lower() or "rel='canonical'" in text.lower(),
        }
    except httpx.HTTPError as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {str(exc)[:240]}"}


@activity.defn
async def collect_technical_evidence(sites: list[dict[str, str]]) -> dict[str, Any]:
    observed_at = datetime.now(UTC).isoformat()
    evidence: list[dict[str, Any]] = []
    headers = {"User-Agent": "AHCP-SEO-Audit/1.0"}
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        for site in sites:
            site_id = str(site.get("site_id") or site.get("site") or "unknown")
            hostname = str(site.get("site") or "").strip().strip("/")
            if not hostname:
                continue
            base = hostname if hostname.startswith("http") else f"https://{hostname}"
            targets = [
                base + "/",
                base + "/robots.txt",
                base + "/sitemap_index.xml",
            ]
            probes = [await _probe(client, target) for target in targets]
            homepage = probes[0]
            robots = probes[1]
            sitemap = probes[2]
            summary = (
                f"Technical probe for {site_id}: homepage={homepage.get('status', 'ERR')}, "
                f"robots={robots.get('status', 'ERR')}, "
                f"sitemap_index={sitemap.get('status', 'ERR')}."
            )
            digest_seed = repr(probes)
            record = Evidence(
                evidence_id=_evidence_id(site_id, digest_seed),
                source="live_http_probe",
                summary=summary,
                site_id=site_id,
                kind="technical_health",
                observed_at=observed_at,
                period_start=None,
                period_end=None,
                source_property=base,
                payload_hash=hashlib.sha256(digest_seed.encode()).hexdigest(),
                payload={"probes": probes},
            )
            evidence.append(record.model_dump(mode="json"))
    return {"evidence": evidence, "note": "Live HTTP technical probes collected.", "errors": []}
