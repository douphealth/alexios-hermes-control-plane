#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"
API_URL="${API_URL:-http://127.0.0.1:8080}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null 2>&1 || fail "docker is required"
command -v curl >/dev/null 2>&1 || fail "curl is required"
[[ -f "$ENV_FILE" ]] || fail "environment file not found: $ENV_FILE"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

MODE="${AUTONOMOUS_GROWTH_MODE:-READ_ONLY}"
ENABLED="${AUTONOMOUS_GROWTH_ENABLED:-false}"

case "$MODE" in
  READ_ONLY|DRAFT|STAGING|PRODUCTION_APPROVED) ;;
  *) fail "invalid AUTONOMOUS_GROWTH_MODE=$MODE" ;;
esac

if [[ "$MODE" != "READ_ONLY" && -z "${WORDPRESS_SITES_JSON:-}" ]]; then
  fail "WORDPRESS_SITES_JSON is required for $MODE"
fi
if [[ "$MODE" == "PRODUCTION_APPROVED" && "${ALLOW_PRODUCTION_WRITES:-false}" != "true" ]]; then
  fail "PRODUCTION_APPROVED requires ALLOW_PRODUCTION_WRITES=true"
fi

printf 'Validating compose configuration...\n'
docker compose --env-file "$ENV_FILE" config --quiet

printf 'Building and starting core control-plane services...\n'
docker compose --env-file "$ENV_FILE" up -d --build postgres temporal api worker

printf 'Repairing rollback backup volume ownership...\n'
docker compose --env-file "$ENV_FILE" run --rm --no-deps --user 0 worker \
  sh -c 'mkdir -p /var/lib/ahcp/backups && chown -R 10001:10001 /var/lib/ahcp/backups'

printf 'Applying idempotent database migrations...\n'
for migration in db/migrations/*.sql; do
  [[ -f "$migration" ]] || fail "migration file missing: $migration"
  name="$(basename "$migration")"
  docker compose --env-file "$ENV_FILE" exec -T postgres \
    psql -v ON_ERROR_STOP=1 -U postgres -d hermes_control_plane \
    < "$migration" >/dev/null
  printf '  applied %s\n' "$name"
done

printf 'Waiting for API health...\n'
for _ in $(seq 1 45); do
  if curl -fsS "$API_URL/healthz" >/tmp/ahcp-health.json; then
    break
  fi
  sleep 2
done
curl -fsS "$API_URL/healthz" >/tmp/ahcp-health.json || fail "API health check failed"
curl -fsS "$API_URL/readyz" >/tmp/ahcp-ready.json || fail "API readiness check failed"

printf 'Verifying worker runtime...\n'
WORKER_ID="$(docker compose --env-file "$ENV_FILE" ps -q worker)"
[[ -n "$WORKER_ID" ]] || fail "worker is not running"

if [[ -n "${GSC_SERVICE_ACCOUNT_FILE:-}" ]]; then
  docker compose --env-file "$ENV_FILE" exec -T worker \
    test -r "$GSC_SERVICE_ACCOUNT_FILE" || fail "worker cannot read GSC credential"
fi

docker compose --env-file "$ENV_FILE" exec -T worker \
  sh -c 'touch /var/lib/ahcp/backups/.acceptance-test && rm /var/lib/ahcp/backups/.acceptance-test' \
  || fail "worker cannot write rollback backup volume"

printf 'Running structured-output provider acceptance...\n'
docker compose --env-file "$ENV_FILE" exec -T worker \
  ahcp-provider-smoke --mode "$MODE" || fail "provider acceptance failed"

printf 'Starting autonomous scheduler after acceptance gates...\n'
docker compose --env-file "$ENV_FILE" up -d scheduler
SCHEDULER_ID="$(docker compose --env-file "$ENV_FILE" ps -q scheduler)"
[[ -n "$SCHEDULER_ID" ]] || fail "scheduler is not running"

docker compose --env-file "$ENV_FILE" ps worker scheduler

printf '\nAUTONOMOUS CONTROL PLANE DEPLOYED\n'
printf 'enabled=%s mode=%s production_writes=%s\n' \
  "$ENABLED" "$MODE" "${ALLOW_PRODUCTION_WRITES:-false}"
printf 'No manual portfolio POST is required when AUTONOMOUS_GROWTH_ENABLED=true.\n'
