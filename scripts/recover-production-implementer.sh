#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
REUSE_SHARED_ROUTER="${REUSE_OPENAI_ROUTER_FOR_DEEPSEEK:-false}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v python3 >/dev/null 2>&1 || fail "python3 is required"
[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"
[[ "$REUSE_SHARED_ROUTER" == "true" ]] || fail \
  "set REUSE_OPENAI_ROUTER_FOR_DEEPSEEK=true to explicitly reuse the existing shared model-router credential"

printf 'Binding implementer to the existing shared model router without printing secrets...\n'
python3 - "$ENV_FILE" <<'PY'
from pathlib import Path
import os
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()
values: dict[str, str] = {}
for line in lines:
    if not line or line.lstrip().startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key] = value

openai_key = values.get("OPENAI_API_KEY", "").strip()
openai_base = values.get("OPENAI_BASE_URL", "").strip()
if not openai_key:
    raise SystemExit("OPENAI_API_KEY is missing; cannot bind implementer to shared router")
if not openai_base:
    raise SystemExit("OPENAI_BASE_URL is missing; cannot bind implementer to shared router")

updates = {
    "DEEPSEEK_API_KEY": openai_key,
    "DEEPSEEK_BASE_URL": openai_base,
    "DEEPSEEK_MODEL": "deepseek-v4-flash",
    "DEEPSEEK_REASONING": "high",
}

out: list[str] = []
seen: set[str] = set()
for line in lines:
    key = line.split("=", 1)[0] if "=" in line else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in seen:
        out.append(f"{key}={value}")

tmp = path.with_suffix(path.suffix + ".implementer.tmp")
tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
os.chmod(tmp, 0o600)
tmp.replace(path)
os.chmod(path, 0o600)
print("IMPLEMENTER_ROUTE_BOUND=shared-router")
print("DEEPSEEK_MODEL=deepseek-v4-flash")
PY

printf 'Running production provider acceptance in a fresh worker container...\n'
docker compose --env-file "$ENV_FILE" run --rm --no-deps worker \
  ahcp-provider-smoke --mode PRODUCTION_APPROVED

printf 'Recreating worker with the accepted production model configuration...\n'
docker compose --env-file "$ENV_FILE" up -d --force-recreate worker

printf 'Recreating autonomous scheduler...\n'
docker compose --env-file "$ENV_FILE" up -d --force-recreate scheduler

printf 'Waiting for worker and scheduler startup...\n'
sleep 5

printf 'Verifying provider acceptance inside the live worker...\n'
docker compose --env-file "$ENV_FILE" exec -T worker \
  ahcp-provider-smoke --mode PRODUCTION_APPROVED

printf 'Verifying live production safety state...\n'
docker compose --env-file "$ENV_FILE" exec -T scheduler python - <<'PY'
from alexios_hermes_control_plane.config import get_settings

s = get_settings()
s.assert_autonomous_write_safety()
if not s.autonomous_growth_enabled:
    raise SystemExit("AUTONOMOUS_GROWTH_ENABLED is false")
if s.autonomous_growth_mode != "PRODUCTION_APPROVED":
    raise SystemExit(f"unexpected mode: {s.autonomous_growth_mode}")
if not s.allow_production_writes:
    raise SystemExit("production writes are disabled")
print("PRODUCTION_STATE_OK")
print("MODE=PRODUCTION_APPROVED")
print("PRODUCTION_WRITES=true")
print(f"MAX_INTERVENTIONS={s.autonomous_max_interventions_per_cycle}")
print(f"MAX_MUTATIONS_PER_SITE={s.autonomous_max_mutations_per_site}")
PY

printf 'Starting or ensuring one immediate production commissioning cycle...\n'
docker compose --env-file "$ENV_FILE" exec -T scheduler python - <<'PY'
import asyncio
from datetime import UTC, datetime

from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.workflows.autonomous import AutonomousGrowthWorkflow


async def main() -> None:
    s = get_settings()
    s.assert_autonomous_write_safety()
    client = await Client.connect(s.temporal_address, namespace=s.temporal_namespace)
    workflow_id = f"autonomous-growth-production-commissioning-{datetime.now(UTC).date().isoformat()}"
    payload = {
        "objective": s.autonomous_growth_objective,
        "mode": "PRODUCTION_APPROVED",
        "notification_chat_id": s.autonomous_notification_chat_id,
        "max_interventions": s.autonomous_max_interventions_per_cycle,
        "max_mutations_per_site": s.autonomous_max_mutations_per_site,
    }
    started = False
    try:
        await client.start_workflow(
            AutonomousGrowthWorkflow.run,
            payload,
            id=workflow_id,
            task_queue=s.temporal_task_queue,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        )
        started = True
    except WorkflowAlreadyStartedError:
        pass
    print(f"PRODUCTION_WORKFLOW_ID={workflow_id}")
    print(f"PRODUCTION_WORKFLOW_STARTED={str(started).lower()}")


asyncio.run(main())
PY

printf 'Recent scheduler state:\n'
docker compose --env-file "$ENV_FILE" logs --since=10m --tail=80 scheduler

printf '\nPRODUCTION_IMPLEMENTER_RECOVERY_OK\n'
