import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from temporalio import activity

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.schemas.execution import (
    MutationReceipt,
    MutationType,
    WordPressMutation,
    WordPressSnapshot,
)

_SUPPORTED_POST_TYPES = ("posts", "pages")


def _site_registry() -> dict[str, dict[str, str]]:
    raw = get_settings().wordpress_sites_json
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("WORDPRESS_SITES_JSON must be a JSON array")
    registry: dict[str, dict[str, str]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError("Each WordPress site entry must be an object")
        site_id = str(item.get("site_id", "")).strip()
        base_url = str(item.get("base_url", "")).strip().rstrip("/")
        username = str(item.get("username", "")).strip()
        password = str(item.get("application_password", "")).strip()
        if not all((site_id, base_url, username, password)):
            raise ValueError("WordPress site entry is missing required fields")
        registry[site_id] = {
            "base_url": base_url,
            "username": username,
            "application_password": password,
        }
    return registry


def _credentials(site_id: str) -> dict[str, str]:
    try:
        return _site_registry()[site_id]
    except KeyError as exc:
        raise ValueError(f"WordPress credentials are not configured for {site_id}") from exc


def _slug_from_url(url: str) -> str:
    path = unquote(urlparse(url).path).strip("/")
    if not path:
        raise ValueError("Homepage mutation is not supported by the guarded WordPress adapter")
    return path.rsplit("/", 1)[-1]


def _hash_snapshot(snapshot: WordPressSnapshot) -> str:
    payload = f"{snapshot.title_raw}\n{snapshot.content_raw}".encode()
    return hashlib.sha256(payload).hexdigest()


def _client(site: dict[str, str]) -> httpx.AsyncClient:
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=settings.wordpress_request_timeout_seconds,
        auth=(site["username"], site["application_password"]),
        follow_redirects=True,
    )


async def _find_target(
    client: httpx.AsyncClient,
    base_url: str,
    slug: str,
) -> tuple[str, dict[str, Any]]:
    fields = "id,link,slug,status,modified_gmt,title,content"
    matches: list[tuple[str, dict[str, Any]]] = []
    for post_type in _SUPPORTED_POST_TYPES:
        endpoint = f"{base_url}/wp-json/wp/v2/{post_type}"
        params = {"slug": slug, "context": "edit", "_fields": fields}
        response = await client.get(endpoint, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"WordPress returned invalid {post_type} collection")
        for item in payload:
            if isinstance(item, dict):
                matches.append((post_type, item))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one WordPress post/page for slug {slug}; found {len(matches)}"
        )
    return matches[0]


@activity.defn
async def wordpress_read_target(site_id: str, target_url: str) -> dict[str, Any]:
    site = _credentials(site_id)
    slug = _slug_from_url(target_url)
    async with _client(site) as client:
        post_type, post = await _find_target(client, site["base_url"], slug)
    title = post.get("title")
    content = post.get("content")
    if not isinstance(title, dict) or not isinstance(content, dict):
        raise ValueError("WordPress edit context did not return raw title/content")
    snapshot = WordPressSnapshot(
        site_id=site_id,
        post_id=int(post["id"]),
        post_type=post_type,
        url=str(post.get("link") or target_url),
        slug=str(post["slug"]),
        status=str(post["status"]),
        title_raw=str(title.get("raw") or ""),
        content_raw=str(content.get("raw") or ""),
        modified_gmt=str(post.get("modified_gmt")) if post.get("modified_gmt") else None,
    )
    return snapshot.model_dump(mode="json")


def _backup_snapshot(snapshot: WordPressSnapshot, mutation_id: str) -> str:
    settings = get_settings()
    root = Path(settings.wordpress_backup_dir)
    root.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch for ch in mutation_id if ch.isalnum() or ch in "-_")[:80]
    path = root / f"{snapshot.site_id}-{snapshot.post_type}-{snapshot.post_id}-{safe_id}.json"
    path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
    return str(path)


def _write_allowed(mutation: WordPressMutation) -> None:
    settings = get_settings()
    if mutation.mutation_type == MutationType.TITLE and not settings.wordpress_allow_title_updates:
        raise PermissionError("WordPress title updates are disabled")
    if (
        mutation.mutation_type == MutationType.CONTENT
        and not settings.wordpress_allow_content_updates
    ):
        raise PermissionError("WordPress content updates are disabled")


def _item_endpoint(base_url: str, post_type: str, post_id: int) -> str:
    if post_type not in _SUPPORTED_POST_TYPES:
        raise ValueError(f"Unsupported WordPress REST post type: {post_type}")
    return f"{base_url}/wp-json/wp/v2/{post_type}/{post_id}"


@activity.defn
async def wordpress_apply_mutation(
    mutation_payload: dict[str, Any], snapshot_payload: dict[str, Any], mode: str
) -> dict[str, Any]:
    settings = get_settings()
    mutation = WordPressMutation.model_validate(mutation_payload)
    snapshot = WordPressSnapshot.model_validate(snapshot_payload)
    if mutation.site_id != snapshot.site_id or mutation.post_id != snapshot.post_id:
        raise ValueError("Mutation target does not match the captured snapshot")
    _write_allowed(mutation)
    if mode == "READ_ONLY":
        raise PermissionError("READ_ONLY mode cannot mutate WordPress")
    if mode == "PRODUCTION_APPROVED" and not settings.allow_production_writes:
        raise PermissionError("Production writes are disabled")

    backup_path = _backup_snapshot(snapshot, mutation.mutation_id)
    body: dict[str, str] = {}
    if mutation.mutation_type == MutationType.TITLE:
        body["title"] = mutation.value
    elif mutation.mutation_type == MutationType.CONTENT:
        body["content"] = mutation.value
    else:
        raise ValueError("Unsupported WordPress mutation type")

    if mode == "DRAFT" and snapshot.status == "publish":
        if not settings.wordpress_allow_status_changes:
            raise PermissionError(
                "DRAFT mode cannot convert a published item while status changes are disabled"
            )
        body["status"] = "draft"

    site = _credentials(mutation.site_id)
    endpoint = _item_endpoint(site["base_url"], snapshot.post_type, mutation.post_id)
    async with _client(site) as client:
        response = await client.post(endpoint, json=body)
        response.raise_for_status()
        updated = response.json()
    encoded = json.dumps(updated, sort_keys=True, default=str).encode()
    after_hash = hashlib.sha256(encoded).hexdigest()
    receipt = MutationReceipt(
        mutation_id=mutation.mutation_id,
        site_id=mutation.site_id,
        post_id=mutation.post_id,
        post_type=snapshot.post_type,
        target_url=mutation.target_url,
        status="APPLIED",
        before_sha256=_hash_snapshot(snapshot),
        after_sha256=after_hash,
        backup_path=backup_path,
    )
    return receipt.model_dump(mode="json")


@activity.defn
async def wordpress_validate_mutation(
    mutation_payload: dict[str, Any], receipt_payload: dict[str, Any]
) -> dict[str, Any]:
    mutation = WordPressMutation.model_validate(mutation_payload)
    receipt = MutationReceipt.model_validate(receipt_payload)
    site = _credentials(mutation.site_id)
    endpoint = _item_endpoint(site["base_url"], receipt.post_type, mutation.post_id)
    async with _client(site) as client:
        response = await client.get(endpoint, params={"context": "edit"})
        response.raise_for_status()
        current = response.json()
    field = "title" if mutation.mutation_type == MutationType.TITLE else "content"
    container = current.get(field) if isinstance(current, dict) else None
    raw = container.get("raw") if isinstance(container, dict) else None
    if raw != mutation.value:
        return receipt.model_copy(
            update={"status": "VALIDATION_FAILED", "validation_error": f"{field} mismatch"}
        ).model_dump(mode="json")
    return receipt.model_copy(update={"status": "VALIDATED"}).model_dump(mode="json")


@activity.defn
async def wordpress_rollback_mutation(receipt_payload: dict[str, Any]) -> dict[str, Any]:
    receipt = MutationReceipt.model_validate(receipt_payload)
    if not receipt.backup_path:
        raise ValueError("Rollback receipt has no backup path")
    backup_path = Path(receipt.backup_path)
    raw_snapshot = await asyncio.to_thread(backup_path.read_text, encoding="utf-8")
    snapshot = WordPressSnapshot.model_validate_json(raw_snapshot)
    site = _credentials(snapshot.site_id)
    endpoint = _item_endpoint(site["base_url"], snapshot.post_type, snapshot.post_id)
    body = {"title": snapshot.title_raw, "content": snapshot.content_raw}
    if get_settings().wordpress_allow_status_changes:
        body["status"] = snapshot.status
    async with _client(site) as client:
        response = await client.post(endpoint, json=body)
        response.raise_for_status()
    return receipt.model_copy(update={"status": "ROLLED_BACK", "rolled_back": True}).model_dump(
        mode="json"
    )
