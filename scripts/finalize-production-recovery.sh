#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"

printf 'Verifying live worker model registry without external provider calls...\n'
docker compose --env-file "$ENV_FILE" exec -T worker python - <<'PY'
from alexios_hermes_control_plane.config import get_settings
from alexios_hermes_control_plane.models.registry import ModelRegistry

required = {
    "diagnostician",
    "strategist",
    "chief_of_staff",
    "verifier",
    "judge",
    "implementer",
}
registry = ModelRegistry(get_settings())
configured = registry.configured_roles()
missing = sorted(required - configured)
if missing:
    raise SystemExit(f"missing model roles: {', '.join(missing)}")
print("LIVE_MODEL_REGISTRY_OK")
print("CONFIGURED_ROLES=" + ",".join(sorted(configured)))
print("IMPLEMENTER_MODEL=" + registry.get("implementer").model)
PY

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

printf 'Ensuring the current production growth and measurement cycle exactly once...\n'
docker compose --env-file "$ENV_FILE" exec -T scheduler python - <<'PY'
import asyncio

from alexios_hermes_control_plane.autonomous_scheduler import run_cycle


growth_id, measurement_id = asyncio.run(run_cycle())
if not growth_id:
    raise SystemExit("autonomous growth cycle was not enabled")
print(f"PRODUCTION_GROWTH_WORKFLOW_ID={growth_id}")
print(f"PRODUCTION_MEASUREMENT_WORKFLOW_ID={measurement_id}")
print("PRODUCTION_CYCLE_ENSURED=true")
PY

printf 'Recent scheduler state:\n'
docker compose --env-file "$ENV_FILE" logs --since=15m --tail=120 scheduler

printf '\nPRODUCTION_FINALIZATION_OK\n'
