"""AXIOM change control for Hermes WordPress writes (protocol axiom-cc v1).

The workflow takes the per-site lock before applying a mutation and gives it back after
validation or rollback (``change_lock_acquire`` / ``change_lock_release``). The apply
activity re-checks that this workflow still holds the lock (``assert_write_allowed``),
so a write can never slip past the gate even if the workflow step is skipped.

Modes (``CHANGE_LOCK_MODE``):
  off      no check at all
  observe  take the lock when possible and record it, but never block a write (default)
  enforce  no lock, no write; if GitHub is unreachable the write is refused
           unless ``CHANGE_LOCK_FAIL_OPEN=true``

The token comes only from ``AXIOM_CC_TOKEN``; it is never logged or returned.
Stale locks are never broken here: a release that fails is logged for a human.
"""

import asyncio
import logging
from typing import Any

from temporalio import activity

from alexios_hermes_control_plane import axiom_cc
from alexios_hermes_control_plane.config import Settings, get_settings

logger = logging.getLogger(__name__)

OWNER_PREFIX = "hermes-control-plane"


def owner_for(workflow_id: str) -> str:
    return f"{OWNER_PREFIX}:{workflow_id}"[:120]


def current_owner() -> str:
    try:
        return owner_for(activity.info().workflow_id or "unknown")
    except RuntimeError:
        return owner_for("unknown")


def site_key(base_url: str) -> str:
    return axiom_cc.norm_site(base_url)


def _client(settings: Settings) -> axiom_cc.Client:
    token = settings.axiom_cc_token.get_secret_value() if settings.axiom_cc_token else ""
    client = axiom_cc.Client(
        repo=settings.axiom_cc_repo,
        issue=settings.axiom_cc_ledger_issue,
        token=token or None,
        timeout=settings.axiom_cc_timeout_seconds,
    )
    # Never fall back to a broad GITHUB_TOKEN from the environment.
    client._token = token
    return client


def _site_for(site_id: str) -> str:
    from alexios_hermes_control_plane.activities.wordpress import _credentials

    return site_key(_credentials(site_id)["base_url"])


async def acquire(
    site: str, owner: str, task: str, scope: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Try to take the site lock. ``allowed`` says whether the caller may write."""
    settings = settings or get_settings()
    mode = settings.change_lock_mode
    base: dict[str, Any] = {"site": site, "mode": mode, "seq": None}
    if mode == "off":
        return {**base, "allowed": True, "reason": "CHANGE_LOCK_OFF"}
    try:
        code, info = await asyncio.to_thread(_client(settings).lock, site, owner, task, scope)
    except axiom_cc.LedgerUnavailable as exc:
        logger.warning("change lock ledger unavailable for %s: %s", site, exc)
        allowed = mode == "observe" or settings.change_lock_fail_open
        reason = "LEDGER_UNAVAILABLE_FAIL_OPEN" if allowed else "LEDGER_UNAVAILABLE"
        return {**base, "allowed": allowed, "reason": reason, "error": str(exc)[:300]}
    if code == axiom_cc.OK:
        return {**base, "allowed": True, "reason": "LOCK_ACQUIRED", "seq": info.get("seq")}
    # The protocol client denies a second lock even for the holder. Temporal may
    # retry this activity after the ref and ledger comment already exist; treating
    # that as a foreign lock would skip the write and never release it.
    held_by = info.get("held_by")
    held_seq = info.get("seq")
    if isinstance(held_by, dict) and held_by.get("owner") == owner and isinstance(held_seq, int):
        logger.info("change lock for %s already held by this owner at seq %s", site, held_seq)
        return {**base, "allowed": True, "reason": "LOCK_ALREADY_HELD", "seq": held_seq}
    logger.warning("change lock for %s held by someone else: %s", site, info)
    return {
        **base,
        "allowed": mode == "observe",
        "reason": "CHANGE_LOCK_HELD",
        "held_by": info.get("held_by") or info.get("why"),
    }


async def release(
    site: str,
    owner: str,
    task: str,
    seq: int | None,
    evidence: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Give back a lock we took. Never raises: a failed release is reported as stale."""
    settings = settings or get_settings()
    if seq is None:
        return {"site": site, "released": False, "reason": "NOT_HELD"}
    try:
        code, info = await asyncio.to_thread(_client(settings).release, site, owner, task, evidence)
    except axiom_cc.LedgerUnavailable as exc:
        logger.error("change lock release failed for %s seq %s (now stale): %s", site, seq, exc)
        return {"site": site, "released": False, "reason": "STALE_RELEASE_FAILED"}
    if code == axiom_cc.OK:
        return {"site": site, "released": True, "seq": seq}
    # A retry can observe the release ref the previous attempt already created.
    if info.get("result") == "NOT_HELD":
        logger.info("change lock for %s seq %s is already released", site, seq)
        return {"site": site, "released": True, "seq": seq, "reason": "ALREADY_RELEASED"}
    logger.error("change lock release refused for %s seq %s: %s", site, seq, info)
    return {"site": site, "released": False, "reason": "RELEASE_REFUSED", "info": info}


async def assert_write_allowed(site: str, owner: str, settings: Settings | None = None) -> None:
    """Raise PermissionError in enforce mode unless ``owner`` holds the lock for ``site``."""
    settings = settings or get_settings()
    if settings.change_lock_mode != "enforce":
        return
    try:
        state = await asyncio.to_thread(_client(settings).state, site)
    except axiom_cc.LedgerUnavailable as exc:
        if settings.change_lock_fail_open:
            logger.warning("change lock unavailable for %s, fail-open is on: %s", site, exc)
            return
        raise PermissionError(f"ledger unavailable: drafts only ({site})") from None
    holder = state.get("holder") or {}
    if not state.get("held") or holder.get("owner") != owner:
        raise PermissionError(f"site {site} is not locked by {owner}; write refused")


@activity.defn
async def change_lock_acquire(site_id: str, task: str, scope: str) -> dict[str, Any]:
    return await acquire(_site_for(site_id), current_owner(), task, scope)


@activity.defn
async def change_lock_release(
    site_id: str, task: str, seq: int | None, evidence: str
) -> dict[str, Any]:
    return await release(_site_for(site_id), current_owner(), task, seq, evidence)
