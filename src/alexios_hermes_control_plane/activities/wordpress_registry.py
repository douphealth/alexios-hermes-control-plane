import json
from typing import Any
from urllib.parse import urlparse

from temporalio import activity

from alexios_hermes_control_plane.config import get_settings


@activity.defn
async def wordpress_resolve_site(target_url: str) -> dict[str, Any]:
    raw = get_settings().wordpress_sites_json
    if not raw:
        raise ValueError("WORDPRESS_SITES_JSON is not configured")
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("WORDPRESS_SITES_JSON must be a JSON array")
    target_host = (urlparse(target_url).hostname or "").lower()
    if not target_host:
        raise ValueError("Intervention target is not an absolute URL")
    matches: list[dict[str, str]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        site_id = str(item.get("site_id", "")).strip()
        base_url = str(item.get("base_url", "")).strip().rstrip("/")
        public_url = str(item.get("public_url", base_url)).strip().rstrip("/")
        public_host = (urlparse(public_url).hostname or "").lower()
        if site_id and public_host == target_host:
            matches.append({"site_id": site_id, "base_url": base_url, "public_url": public_url})
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one configured WordPress site for host {target_host}")
    return matches[0]
