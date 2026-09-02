#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost:8080}"
ENV_FILE="${ENV_FILE:-.env}"
OBJECTIVE="${OBJECTIVE:-Find the 3 highest-leverage portfolio interventions using live first-party GSC evidence across the configured portfolio}"
IDEMPOTENCY_KEY="${IDEMPOTENCY_KEY:-v03-first-live-readonly}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_command docker
require_command curl
require_command python3

[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

[[ "${ALLOW_PRODUCTION_WRITES:-false}" == "false" ]] || \
  fail "ALLOW_PRODUCTION_WRITES must remain false for this deployment"

GSC_HOST_FILE="${GSC_SERVICE_ACCOUNT_HOST_FILE:-./secrets/gsc-service-account.json}"
[[ -f "$GSC_HOST_FILE" ]] || fail "GSC credential file not found: $GSC_HOST_FILE"
[[ -r "$GSC_HOST_FILE" ]] || fail "GSC credential file is not readable: $GSC_HOST_FILE"

python3 - "$GSC_HOST_FILE" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"ERROR: invalid GSC credential JSON: {exc}") from exc

required = {"type", "client_email", "private_key", "token_uri"}
missing = sorted(required.difference(payload))
if missing:
    raise SystemExit(f"ERROR: GSC credential JSON missing fields: {', '.join(missing)}")
if payload.get("type") != "service_account":
    raise SystemExit("ERROR: GSC credential must be a service_account JSON file")
PY

printf 'Validating compose configuration...\n'
docker compose --env-file "$ENV_FILE" config --quiet

printf 'Building and starting services...\n'
docker compose --env-file "$ENV_FILE" up -d --build

printf 'Waiting for API health...\n'
for _ in $(seq 1 30); do
  if curl -fsS "$API_URL/healthz" >/tmp/ahcp-health.json; then
    break
  fi
  sleep 2
done
curl -fsS "$API_URL/healthz" >/tmp/ahcp-health.json || fail "healthz did not become healthy"

python3 - /tmp/ahcp-health.json <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("status") != "ok":
    raise SystemExit(f"ERROR: unhealthy API response: {payload}")
if payload.get("production_writes_enabled") is not False:
    raise SystemExit(f"ERROR: production writes are not disabled: {payload}")
PY

printf 'Checking readiness...\n'
curl -fsS "$API_URL/readyz" >/tmp/ahcp-ready.json || fail "readyz request failed"
python3 - /tmp/ahcp-ready.json <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("status") != "ready" or payload.get("database") is not True:
    raise SystemExit(f"ERROR: service is not ready: {payload}")
PY

printf 'Verifying GSC credential mount inside worker...\n'
docker compose --env-file "$ENV_FILE" exec -T worker \
  test -r "${GSC_SERVICE_ACCOUNT_FILE:-/run/secrets/gsc-service-account.json}" || \
  fail "worker cannot read mounted GSC credential"

printf 'Starting first READ_ONLY portfolio run...\n'
RUN_RESPONSE="$(curl -fsS -X POST "$API_URL/v1/runs/portfolio" \
  -H 'content-type: application/json' \
  -H "Idempotency-Key: $IDEMPOTENCY_KEY" \
  --data "$(python3 - "$OBJECTIVE" <<'PY'
import json
import sys
print(json.dumps({"objective": sys.argv[1], "mode": "READ_ONLY"}))
PY
)")" || fail "failed to start READ_ONLY run"

printf '%s\n' "$RUN_RESPONSE"
RUN_ID="$(python3 - "$RUN_RESPONSE" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
run_id = payload.get("run_id")
if not isinstance(run_id, str) or not run_id:
    raise SystemExit("ERROR: run_id missing from API response")
print(run_id)
PY
)"

printf 'READ_ONLY run started successfully: %s\n' "$RUN_ID"
printf 'Inspect with: curl -fsS %s/v1/runs/%s\n' "$API_URL" "$RUN_ID"
