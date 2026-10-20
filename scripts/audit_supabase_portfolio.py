#!/usr/bin/env python3
"""Read-only Supabase portfolio audit. Does not modify projects, repos or secrets."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

GH = "https://api.github.com"
MANAGEMENT = "https://api.supabase.com/v1"


def get_json(url: str, token: str | None = None) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "supabase-portfolio-audit"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=18) as response:
        return json.load(response)


def parse_config(text: str) -> tuple[str | None, list[str]]:
    match = re.search(r'^\s*project_id\s*=\s*"([^"]+)"', text, re.MULTILINE)
    ref = match.group(1) if match else None
    if ref in ("default", "your-project-ref"):
        ref = None
    unverified = []
    for section in re.split(r"(?=^\[)", text, flags=re.MULTILINE):
        name = re.search(r"^\[functions\.([\w-]+)\]", section, re.MULTILINE)
        if name and re.search(r"^\s*verify_jwt\s*=\s*false\s*$", section, re.MULTILINE):
            unverified.append(name.group(1))
    return ref, unverified


def is_supabase_repo(paths: set[str]) -> bool:
    return any(
        path.startswith("supabase/")
        or "/integrations/supabase/" in path
        or path.endswith(("/supabase.ts", "/supabaseClient.ts", "/SupabaseSyncProvider.tsx"))
        or "/infrastructure/supabase/" in path
        for path in paths
    )


def list_repos(owner: str, gh_token: str | None, include_private: bool) -> list[dict]:
    if include_private and not gh_token:
        raise ValueError("--include-private needs PORTFOLIO_GITHUB_TOKEN")
    base = (
        f"{GH}/user/repos?affiliation=owner&per_page=100"
        if include_private else f"{GH}/users/{quote(owner)}/repos?per_page=100"
    )
    repos: list[dict] = []
    page = 1
    while True:
        batch = get_json(f"{base}&page={page}", gh_token)
        if not isinstance(batch, list):
            raise ValueError("Unexpected GitHub response")
        repos.extend(x for x in batch if x.get("owner", {}).get("login", "").lower() == owner.lower())
        if len(batch) < 100:
            break
        page += 1
    return repos


def inspect_repo(repo: dict, gh_token: str | None) -> dict:
    name = repo["full_name"]
    branch = quote(repo.get("default_branch", "main"), safe="")
    result: dict = {
        "repository": name, "supabase": False, "project": None,
        "edge_functions": 0, "gateway_jwt_disabled": [],
        "committed_env": False, "error": None,
    }
    try:
        tree = get_json(f"{GH}/repos/{name}/git/trees/{branch}?recursive=1", gh_token)
        if not isinstance(tree, dict):
            raise ValueError("Unexpected tree")
        paths = {item["path"] for item in tree.get("tree", []) if item.get("type") == "blob"}
        result["supabase"] = is_supabase_repo(paths)
        result["committed_env"] = any(
            path.split("/")[-1] in (".env", ".env.local", ".env.production", ".env.development")
            for path in paths
        )
        result["edge_functions"] = sum(
            p.startswith("supabase/functions/") and p.endswith("/index.ts") for p in paths
        )
        if tree.get("truncated"):
            result["error"] = "Tree truncated; incomplete inspection"
        if "supabase/config.toml" in paths:
            cfg = get_json(
                f"{GH}/repos/{name}/contents/supabase/config.toml?ref={branch}", gh_token
            )
            if not isinstance(cfg, dict) or cfg.get("encoding") != "base64":
                raise ValueError("Unexpected config format")
            decoded = base64.b64decode(cfg["content"]).decode("utf-8")
            result["project"], result["gateway_jwt_disabled"] = parse_config(decoded)
        if result["supabase"] and not result["project"]:
            result["note"] = "Supabase detected, no usable project reference in config"
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as exc:
        result["error"] = f"{type(exc).__name__}: check permissions or API limits"
    return result


def probe(ref: str) -> str:
    """Public reachability probe only; never proves database or payment health."""
    request = Request(
        f"https://{ref}.supabase.co/auth/v1/health",
        headers={"User-Agent": "supabase-portfolio-audit"},
    )
    try:
        with urlopen(request, timeout=10) as response:
            return f"http_{response.status}_reachable"
    except HTTPError as exc:
        return (
            f"http_{exc.code}_auth_required"
            if exc.code in (401, 403) else f"http_{exc.code}_unverified"
        )
    except (URLError, TimeoutError):
        return "unreachable_or_network_error"


def management_projects(token: str | None) -> dict[str, str] | None:
    if not token:
        return None
    data = get_json(f"{MANAGEMENT}/projects", token)
    if not isinstance(data, list):
        raise ValueError("Unexpected Supabase management response")
    return {x["id"]: str(x.get("status", "UNKNOWN")) for x in data if x.get("id")}


def make_report(rows: list[dict], projects: dict[str, str] | None, owner: str) -> str:
    used = [r for r in rows if r["supabase"]]
    refs = {r["project"] for r in used if r["project"]}
    lines = [
        f"# Supabase portfolio recovery audit: {owner}",
        "",
        f"Generated UTC: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        "",
        f"Repositories checked: {len(rows)}",
        f"Repositories with Supabase code/config evidence: {len(used)}",
        f"Distinct configured project references: {len(refs)}",
        f"Repositories tracking potentially sensitive .env files: {sum(r['committed_env'] for r in rows)}",
        f"Incomplete repository inspections: {sum(bool(r['error']) for r in rows)}",
        "",
        "Missing management access DOES NOT prove a project was deleted. "
        "HTTP 401/403 means the Auth endpoint responds, not that the database works.",
        "",
        "| Repository | Ref | Management status | Auth reachability | Functions | JWT-disabled | .env tracked |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for row in sorted(used, key=lambda x: x["repository"]):
        ref = row["project"]
        status = (
            projects.get(ref, "NOT IN AUTHORIZED ACCOUNT") if projects is not None and ref
            else "unverified"
        )
        lines.append(
            f"| {row['repository']} | {ref or 'UNRESOLVED'} | {status} | "
            f"{row.get('reachability', 'not probed')} | {row['edge_functions']} | "
            f"{len(row['gateway_jwt_disabled'])} | {'YES' if row['committed_env'] else 'no'} |"
        )
    lines.extend([
        "",
        "## Required recovery sequence",
        "",
        "1. Restore access to the ORIGINAL Supabase organization and project IDs.",
        "2. Record project status and back up data before any migration or schema change.",
        "3. Review gateway-JWT-disabled functions for independent authentication and rate limiting.",
        "4. Privately inspect committed .env values; rotate ONLY confirmed exposed secrets.",
        "5. Deploy missing Edge Functions to verified project IDs using reviewed changes.",
        "6. Verify Auth, RLS, data operations, Stripe payments, webhooks, and entitlement recovery.",
        "",
        "This auditor is GET-only. It never reads .env contents, updates databases, or deploys code.",
        "",
    ])
    for row in rows:
        if row["error"]:
            lines.append(f"INCOMPLETE: {row['repository']} - {row['error']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", default="douphealth")
    parser.add_argument("--output", default="reports/supabase-portfolio-audit.md")
    parser.add_argument("--json-output", default="reports/supabase-portfolio-audit.json")
    parser.add_argument("--include-private", action="store_true")
    parser.add_argument("--skip-probes", action="store_true")
    args = parser.parse_args()
    gh_token = os.environ.get("PORTFOLIO_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN")
    try:
        repos = list_repos(args.owner, gh_token, args.include_private)
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(pool.map(lambda r: inspect_repo(r, gh_token), repos))
        refs = sorted({r["project"] for r in rows if r["project"]})
        if not args.skip_probes:
            with ThreadPoolExecutor(max_workers=6) as pool:
                checked = dict(zip(refs, pool.map(probe, refs)))
            for row in rows:
                if row["project"]:
                    row["reachability"] = checked[row["project"]]
        try:
            managed = management_projects(os.environ.get("SUPABASE_ACCESS_TOKEN"))
        except (HTTPError, URLError, ValueError, TimeoutError):
            managed = None
            print("Supabase Management API unavailable; statuses unverified.")
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(make_report(rows, managed, args.owner), encoding="utf-8")
        json_path = Path(args.json_output)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Audited {len(rows)} repos. Saved {output} and {json_path}.")
        return 1 if any(r["error"] for r in rows) else 0
    except (HTTPError, URLError, ValueError, TimeoutError) as exc:
        print(f"Audit failed: {type(exc).__name__}; verify access and network.")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
