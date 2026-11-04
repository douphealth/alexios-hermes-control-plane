from collections.abc import Iterator
from typing import Any

import pytest
from axiom_cc_mock import start
from pydantic import SecretStr

from alexios_hermes_control_plane import axiom_cc
from alexios_hermes_control_plane.activities import change_lock
from alexios_hermes_control_plane.config import Settings

TOKEN = "tok-HERMES-SECRET-987"
SITE = "gearuptofit.com"
ME = change_lock.owner_for("wf-1")
OTHER = "AXIOM-SEARCH"


@pytest.fixture
def github() -> Iterator[tuple[Any, str]]:
    srv, state, url = start()
    yield state, url
    srv.shutdown()
    srv.server_close()


def _settings(url: str, mode: str = "enforce", **extra: Any) -> Settings:
    settings = Settings(
        _env_file=None,
        change_lock_mode=mode,
        axiom_cc_token=SecretStr(TOKEN),
        axiom_cc_repo="o/r",
        axiom_cc_ledger_issue=1,
        axiom_cc_timeout_seconds=5,
        **extra,
    )
    return settings


@pytest.fixture(autouse=True)
def _api(monkeypatch: pytest.MonkeyPatch, github: tuple[Any, str]) -> None:
    monkeypatch.setattr(axiom_cc, "API", github[1])
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("AXIOM_CC_TOKEN", raising=False)


def test_site_key_normalizes_wordpress_base_url() -> None:
    assert change_lock.site_key("https://www.GearUpToFit.com/") == SITE


def test_defaults_are_observe_and_fail_closed() -> None:
    settings = Settings(_env_file=None)
    assert settings.change_lock_mode == "observe"
    assert settings.change_lock_fail_open is False


async def test_enforce_acquire_write_release(github: tuple[Any, str]) -> None:
    settings = _settings(github[1])
    lock = await change_lock.acquire(SITE, ME, "m1", "1 URL", settings)
    assert lock["allowed"] and lock["seq"] == 1
    await change_lock.assert_write_allowed(SITE, ME, settings)
    done = await change_lock.release(SITE, ME, "m1", lock["seq"], "ok", settings)
    assert done["released"] is True
    with pytest.raises(PermissionError, match="not locked"):
        await change_lock.assert_write_allowed(SITE, ME, settings)


async def test_enforce_denies_when_another_party_holds_the_lock(
    github: tuple[Any, str],
) -> None:
    settings = _settings(github[1])
    other = await change_lock.acquire(SITE, OTHER, "t", "1 URL", settings)
    assert other["allowed"]
    lock = await change_lock.acquire(SITE, ME, "m1", "1 URL", settings)
    assert lock["allowed"] is False
    assert lock["reason"] == "CHANGE_LOCK_HELD"
    assert lock["held_by"]["owner"] == OTHER
    with pytest.raises(PermissionError):
        await change_lock.assert_write_allowed(SITE, ME, settings)
    # we never release someone else's lock
    refused = await change_lock.release(SITE, ME, "m1", 1, "x", settings)
    assert refused["released"] is False


async def test_observe_never_blocks_but_still_records(github: tuple[Any, str]) -> None:
    settings = _settings(github[1], mode="observe")
    await change_lock.acquire(SITE, OTHER, "t", "", settings)
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    assert lock["allowed"] is True and lock["seq"] is None
    await change_lock.assert_write_allowed(SITE, ME, settings)


async def test_enforce_fails_closed_when_ledger_unavailable(github: tuple[Any, str]) -> None:
    github[0].down = True
    settings = _settings(github[1])
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    assert lock == {**lock, "allowed": False, "reason": "LEDGER_UNAVAILABLE"}
    with pytest.raises(PermissionError, match="drafts only"):
        await change_lock.assert_write_allowed(SITE, ME, settings)
    stale = await change_lock.release(SITE, ME, "m1", 1, "", settings)
    assert stale["reason"] == "STALE_RELEASE_FAILED"


async def test_fail_open_is_an_explicit_switch(github: tuple[Any, str]) -> None:
    github[0].down = True
    settings = _settings(github[1], change_lock_fail_open=True)
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    assert lock["allowed"] is True and lock["reason"] == "LEDGER_UNAVAILABLE_FAIL_OPEN"
    await change_lock.assert_write_allowed(SITE, ME, settings)


async def test_no_token_fails_closed_and_ignores_github_token(
    github: tuple[Any, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    settings = Settings(
        _env_file=None,
        change_lock_mode="enforce",
        axiom_cc_repo="o/r",
        axiom_cc_ledger_issue=1,
    )
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    assert lock["allowed"] is False and lock["reason"] == "LEDGER_UNAVAILABLE"
    assert github[0].refs == {}


async def test_off_mode_skips_github_entirely(github: tuple[Any, str]) -> None:
    github[0].down = True
    settings = _settings(github[1], mode="off")
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    assert lock["allowed"] is True
    await change_lock.assert_write_allowed(SITE, ME, settings)


async def test_same_owner_reacquire_and_rerelease_are_idempotent(
    github: tuple[Any, str],
) -> None:
    settings = _settings(github[1])
    first = await change_lock.acquire(SITE, ME, "m1", "1 URL", settings)
    again = await change_lock.acquire(SITE, ME, "m1", "1 URL", settings)
    assert again["allowed"] is True
    assert again["reason"] == "LOCK_ALREADY_HELD"
    assert again["seq"] == first["seq"] == 1
    assert len([ref for ref in github[0].refs if "/lock/" in ref]) == 1
    await change_lock.assert_write_allowed(SITE, ME, settings)
    done = await change_lock.release(SITE, ME, "m1", again["seq"], "ok", settings)
    assert done["released"] is True
    repeated = await change_lock.release(SITE, ME, "m1", again["seq"], "ok", settings)
    assert repeated["released"] is True
    assert repeated["reason"] == "ALREADY_RELEASED"
    assert len([ref for ref in github[0].refs if "/release/" in ref]) == 1
    assert TOKEN not in repr(again)
    assert TOKEN not in repr(repeated)


async def test_token_never_leaks_into_results_or_ledger(github: tuple[Any, str]) -> None:
    settings = _settings(github[1])
    lock = await change_lock.acquire(SITE, ME, "m1", "", settings)
    await change_lock.release(SITE, ME, "m1", lock["seq"], "", settings)
    assert TOKEN not in repr(lock)
    assert TOKEN not in repr(settings)
    assert all(TOKEN not in str(c) for c in github[0].comments)
