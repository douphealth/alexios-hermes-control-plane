# Alexios Hermes Control Plane

Durable, API-first orchestration for **Alexios Hermes Intelligence OS**.

Telegram is the human interface, not the inter-agent message bus. Temporal owns durable orchestration and retries. PostgreSQL/pgvector owns machine state. Each model provider sits behind a typed adapter. Agent outputs are schema-validated before they can enter workflow state.

## Current status — v0.3

Implemented:

- one Telegram webhook as the operator entry point;
- one durable Temporal `PortfolioOptimizationWorkflow` with history-aware context;
- canonical 9-site portfolio registry with stable `site_id`, domain and GSC property identity;
- first-party Google Search Console evidence ingestion using read-only service-account auth;
- current-vs-previous Search Analytics windows plus top-page and top-query evidence;
- deterministic evidence IDs, canonical payload hashes and provenance fields (`site_id`, kind,
  observation time, period, source property);
- three specialist calls in parallel: GLM diagnostician, GPT-5.6 Terra strategist, GPT-5.6 Luna state/triage;
- independent GLM Flash verifier gate: every specialist finding is audited against supplied evidence;
- **fail-closed decision eligibility in application code**: UNGROUNDED and UNVERIFIED findings
  are removed before the judge is invoked; PARTIAL findings receive a deterministic 50% confidence
  penalty; a run may safely return zero interventions if nothing clears the gate;
- GPT-5.6 Sol final judge selecting a maximum of three interventions, with a deterministic
  decision score computed in code (impact × confidence × revenue alignment ÷ (effort ×
  time-to-signal) × reversibility);
- operator feedback loop: `/feedback <run-prefix> <rank> <VERDICT> [note]` on Telegram records
  verdicts (ADOPTED / REJECTED / EXECUTED_VERIFIED / EXECUTED_NO_SIGNAL / PARTIAL); the last
  50 verdicts are injected into every future run;
- run history injection: the last 10 completed runs' objectives and chosen interventions are
  part of every run's context;
- native OpenAI Responses API + Pydantic Structured Outputs for Luna/Terra/Sol;
- DeepSeek Responses API JSON-Schema adapter for `deepseek-v4-flash`;
- explicit GLM OpenAI-compatible adapter, with no silent provider fallback;
- PostgreSQL/pgvector execution ledger with per-agent latency/token telemetry;
- idempotent Telegram-triggered workflow IDs to prevent duplicate runs on webhook retries;
- final Telegram completion/failure notification;
- strict Pydantic contracts between workflow activities;
- production mutations disabled by default;
- Docker Compose local stack using Temporal's current CLI development server;
- CI with Ruff, strict mypy, pytest and Compose validation.

Intentionally **not** enabled yet: autonomous production writes, Redis/Celery, LangGraph, Neo4j,
or E2B. Evidence quality, approval signals, rollback, write locks and independent post-write
verification must clear first.

## Architecture

```text
Alexios
  |
Telegram (/portfolio, /feedback)
  |
FastAPI gateway
  |
Temporal workflow
  |-- context: canonical site registry + GSC evidence + run history + feedback + operating rules
  |-- GLM 5.3 diagnostician -------\
  |-- GPT-5.6 Terra strategist -----+--> GLM 5.3 Flash verifier
  |-- GPT-5.6 Luna state triage ----/             |
  |                                      deterministic eligibility gate
  |                                                  |
  `--------------------------------------------> GPT-5.6 Sol judge --> result
  |
PostgreSQL + pgvector ledger
  |
Telegram completion notification
```

DeepSeek V4 Flash is registered as the implementation engine but deliberately unused in the
read-only workflow.

## Safety invariants

1. `READ_ONLY` is the default run mode.
2. `ALLOW_PRODUCTION_WRITES=false` is the default hard gate.
3. Production Telegram requires both a webhook secret and an explicit user allowlist.
4. LLMs never generate database mutation instructions; application code owns persistence.
5. Agent identity/model identity is assigned by the orchestrator, not trusted from model output.
6. Webhook retries are idempotent.
7. There is no hidden model routing or silent fallback.
8. Provider secrets and Google service-account credentials are host configuration and must never be committed.
9. UNGROUNDED or UNVERIFIED findings cannot become interventions even if the verifier is unavailable.

## GSC evidence configuration

Use an existing Google service-account JSON that already has read access to the relevant Search
Console properties. Mount it on the host/container and configure only its path:

```bash
GSC_SERVICE_ACCOUNT_FILE=/run/secrets/gsc-service-account.json
GSC_LOOKBACK_DAYS=28
GSC_ROW_LIMIT=250
GSC_MAX_SITES_PER_RUN=12
```

The connector requests only the `webmasters.readonly` OAuth scope. Credential contents are never
stored in prompts, the ledger, Git, or model requests. If GSC is not configured, collection returns
an explicit disabled note and the evidence bar remains fail-closed.

## Local development

```bash
cp .env.example .env
# Fill only the credentials/endpoints you actually use.
docker compose up --build
```

Endpoints:

- API: `http://localhost:8080`
- health: `GET /healthz`
- readiness: `GET /readyz`
- Temporal UI: `http://localhost:8233`

Start a portfolio run without Telegram:

```bash
curl -X POST http://localhost:8080/v1/runs/portfolio \
  -H 'content-type: application/json' \
  -H 'Idempotency-Key: manual-test-001' \
  -d '{"objective":"Find the 3 highest-leverage portfolio interventions","mode":"READ_ONLY"}'
```

Read the run from the ledger:

```bash
curl http://localhost:8080/v1/runs/<run-id>
```

Telegram:

```text
/portfolio Find the three highest-leverage portfolio interventions

/feedback <run-prefix> 1 EXECUTED_VERIFIED clicks +18% on the sitemap fix
```

## Model routing

| Role | Default model | Interface |
|---|---|---|
| chief of staff / triage | `gpt-5.6-luna` | OpenAI Responses + structured parse |
| strategist | `gpt-5.6-terra` | OpenAI Responses + structured parse |
| final judge | `gpt-5.6-sol` | OpenAI Responses + structured parse |
| diagnostician | `glm-5.3` | configured OpenAI-compatible endpoint |
| verifier | `glm-5.3-flash` | configured OpenAI-compatible endpoint |
| implementer (reserved) | `deepseek-v4-flash` | Responses API + JSON Schema |

No role exists until its required credential/endpoint is configured.

## Next stage

After v0.3 is validated with live GSC data, add evidence sources in this order:

1. GA4 organic sessions, conversions and revenue-aligned events;
2. Bing Webmaster data;
3. WordPress read-only inventory, canonical/meta/schema state and rendered HTTP evidence;
4. GitHub/repository/deployment state;
5. persist normalized evidence snapshots in PostgreSQL for longitudinal comparisons;
6. URL Inspection for prioritized URLs only;
7. PR-based implementation with approval, rollback, write locks and independent verification.

Do not enable production writes until the write/rollback/verification path is implemented and tested.
