#!/usr/bin/env python3
from __future__ import annotations

import base64
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

WORDPRESS_SITES = [
    ("gearuptofit", "https://gearuptofit.com"),
    ("affiliatemarketingforsuccess", "https://affiliatemarketingforsuccess.com"),
    ("plantastichaven", "https://plantastichaven.com"),
    ("gearuptogrow", "https://gearuptogrow.com"),
    ("mysticaldigits", "https://mysticaldigits.com"),
    ("frenchyfab", "https://frenchyfab.com"),
    ("micegoneguide", "https://micegoneguide.com"),
    ("efficientgptprompts", "https://efficientgptprompts.com"),
]

NON_WORDPRESS_SITES = [
    ("openclaw-skillshub", "https://openclaw-skillshub.com", "github-static"),
]


def _auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return f"Basic {token}"


def _validate(base_url: str, username: str, password: str) -> tuple[bool, str]:
    url = f"{base_url.rstrip('/')}/wp-json/wp/v2/users/me?context=edit"
    request = Request(
        url,
        headers={
            "Authorization": _auth_header(username, password),
            "User-Agent": "ALEXIOS-HERMES-Control-Plane/production-commissioning",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode())
        if not isinstance(payload, dict) or not payload.get("id"):
            return False, "unexpected WordPress response"
        return True, str(payload.get("name") or payload.get("slug") or payload["id"])
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, f"network error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def _replace_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in values:
            output.append(f"{key}={values[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in values.items():
        if key not in seen:
            output.append(f"{key}={value}")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def main() -> int:
    env_path = Path(sys.argv[1] if len(sys.argv) > 1 else ".env")
    entries: list[dict[str, str]] = []

    print("Secure WordPress production commissioning")
    print("Credentials are entered locally and are never echoed.")
    print(
        f"All {len(WORDPRESS_SITES)} WordPress sites must pass REST authentication "
        "before production mode is enabled."
    )
    for site_id, base_url, adapter in NON_WORDPRESS_SITES:
        print(
            f"SKIP: {site_id} {base_url} is {adapter}; "
            "it stays in portfolio intelligence but is not commissioned through WordPress REST."
        )
    print()

    for site_id, base_url in WORDPRESS_SITES:
        print(f"[{site_id}] {base_url}")
        username = input("WordPress username: ").strip()
        password = getpass.getpass("Application Password: ").strip()
        if not username or not password:
            print("FAIL: username/application password is required", file=sys.stderr)
            return 2
        ok, detail = _validate(base_url, username, password)
        if not ok:
            print(f"FAIL: {site_id}: {detail}", file=sys.stderr)
            print("Production mode was NOT enabled.", file=sys.stderr)
            return 3
        print(f"PASS: authenticated as {detail}\n")
        entries.append(
            {
                "site_id": site_id,
                "public_url": base_url,
                "base_url": base_url,
                "username": username,
                "application_password": password,
            }
        )

    values = {
        "WORDPRESS_SITES_JSON": json.dumps(entries, separators=(",", ":")),
        "AUTONOMOUS_GROWTH_ENABLED": "true",
        "AUTONOMOUS_GROWTH_MODE": "PRODUCTION_APPROVED",
        "ALLOW_PRODUCTION_WRITES": "true",
        "AUTONOMOUS_GROWTH_INTERVAL_HOURS": "24",
        "AUTONOMOUS_MAX_INTERVENTIONS_PER_CYCLE": "3",
        "AUTONOMOUS_MAX_MUTATIONS_PER_SITE": "1",
        "WORDPRESS_ALLOW_TITLE_UPDATES": "true",
        "WORDPRESS_ALLOW_CONTENT_UPDATES": "true",
        "WORDPRESS_ALLOW_STATUS_CHANGES": "false",
    }
    _replace_env(env_path, values)
    print("ALL WORDPRESS AUTH CHECKS PASSED")
    print(f"Production configuration written securely to {env_path}")
    print("mode=PRODUCTION_APPROVED production_writes=true max_mutations_per_site=1")
    print(
        "openclaw-skillshub remains portfolio-visible and analysis-enabled; "
        "live writes require a separate GitHub/static-site adapter."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
