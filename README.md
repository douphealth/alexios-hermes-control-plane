# Alexios Hermes Control Plane

Durable, API-first orchestration for **Alexios Hermes Intelligence OS**.

Telegram is the human interface, not the inter-agent message bus. Temporal owns durable orchestration and retries. PostgreSQL/pgvector owns machine state. Each model provider sits behind a typed adapter. Agent outputs are schema-validated before they can enter workflow state.

## Current status — v0.2

Implemented:

- one Telegram webhook as the operator entry point;
- one durable Temporal `PortfolioOptimizationWorkflow` with history-aware context;
- three specialist calls in parallel: GLM diagnostician, GPT-5.6 Terra strategist, GPT-5.6 Luna state/triage;
- independent GLM Flash verifier gate: every specialist finding is audited against the evidence
  set and stamped GROUNDED / PARTIAL / UNGROUNDED before the judge sees it (fail-open);
- GPT-5.6 Sol final judge selecting a maximum of three interventions, with a deterministic
  decision score computed in code (impact × confidence × revenue alignment ÷ (effort ×
  time-to-signal) × reversibility) so rankings are reproducible and prompt versions are
  comparable experiments;
- operator feedback loop: `/feedback <run-prefix> <rank> <VERDICT> [note]` on Telegram records
  verdicts (ADOPTED / REJECTED / EXECUTED_VERIFIED / EXECUTED_NO_SIGNAL / PARTIAL); the last
  50 verdicts are injected into every future run as feedback memory, so the system stops
  recommending what the operator keeps rejecting and learns demonstrated preferences;
- run history injection: the last 10 completed runs' objectives and chosen interventions are
  part of every run's context, so recommendations do not repeat or contradict recent work;
- portfolio site registry + operating rules (8 sites, env-overridable via `PORTFOLIO_SITES_JSON`)
  injected into every agent context — the agents reason over the real portfolio, not a void;
- native OpenAI Responses API + Pydantic Structured Outputs for Luna/Terra/Sol;
- DeepSeek Responses API JSON-Schema adapter for `deepseek-v4-flash`;
- explicit GLM OpenAI-compatible adapter, with no silent provider fallback;
- PostgreSQL/pgvector execution ledger with per-agent latency/token telemetry;
- idempotent Telegram-triggered workflow IDs to prevent duplicate runs on webhook retries;
- final Telegram completion/failure notification;
- strict Pydantic contracts between workflow activities;
- production mutations disabled by default;
- Docker Compose local stack using Temporal's current CLI development server;
- CI with Ruff, mypy and pytest.

Intentionally **not** added yet: Redis/Celery, LangGraph, Neo4j, E2B, or autonomous production writes. They are unnecessary until measured evidence proves a need.

## Architecture (v0.2)

```text
Alexios
  |
Telegram (/portfolio, /feedback)
  |
FastAPI gateway
  |
Temporal workflow
  |-- context: site registry + run history + feedback memory + operating rules
  |-- GLM 5.3 diagnostician -------\
  |-- GPT-5.6 Terra strategist -----+--> GLM 5.3 Flash verifier --> GPT-5.6 Sol judge --> result
  `-- GPT-5.6 Luna state triage ----/
  |
PostgreSQL + pgvector ledger
  |
Telegram completion notification
```

DeepSeek V4 Flash is registered as the implementation engine but deliberately unused in the read-only workflow. GLM 5.3 Flash is now active as the independent verifier.

## Safety invariants

1. `READ_ONLY` is the default run mode.
2. `ALLOW_PRODUCTION_WRITES=false` is the default hard gate.
3. Production Telegram requires both a webhook secret and an explicit user allowlist.
4. LLMs never generate database mutation instructions; application code owns persistence.
5. Agent identity/model identity is assigned by the orchestrator, not trusted from model output.
6. Webhook retries are idempotent.
7. There is no hidden model routing or silent fallback.
8. Provider secrets are environment variables and must never be committed.

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

### Feedback loop

Every completion message lists numbered interventions. Reply `/feedback <run-prefix> <rank>
<VERDICT> [note]` — the run prefix (any unique leading fragment of the run id) is enough.
Verdicts land in `intervention_feedback`, and the next run's chief-of-staff and judge see the
last 50 verdicts as ground truth about operator preference and past outcomes. This is how the
prompt system compounds instead of repeating itself.

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

The next production milestone is **first-party evidence ingestion**:

1. GSC Search Analytics and URL Inspection where available;
2. GA4 organic/conversion metrics;
3. Bing Webmaster data;
4. WordPress read-only inventory and rendered-state evidence;
5. GitHub/repository/deployment state;
6. deterministic evidence IDs stored in PostgreSQL;
7. only then Playwright/HTTP/schema verification and PR-based implementation.

Do not enable production writes until evidence ingestion, approval signals, rollback, write locks, and independent verification are implemented and tested.
