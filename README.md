# Alexios Hermes Control Plane

Durable, API-first orchestration for **Alexios Hermes Intelligence OS**.

Telegram is the human interface, not the inter-agent message bus. Temporal owns durable orchestration and retries. PostgreSQL/pgvector owns machine state and evidence provenance. Each model provider sits behind a typed adapter. Agent outputs are schema-validated before they can enter workflow state.

## Current status — v0.3

Implemented:

- one Telegram webhook as the operator entry point;
- one durable Temporal `PortfolioOptimizationWorkflow` with history-aware context;
- three specialist calls in parallel: GLM diagnostician, GPT-5.6 Terra strategist, GPT-5.6 Luna state/triage;
- canonical 9-site portfolio registry with stable `site_id`, domain and GSC property identity;
- first-party Google Search Console Search Analytics ingestion using read-only service-account auth;
- authorized GSC property discovery with domain-property preference and URL-prefix fallback;
- exact current-vs-previous-period aggregate GSC metrics plus capped page/query opportunity mining;
- typed evidence provenance (`site_id`, kind, observation time, period, property and payload hash);
- deterministic evidence IDs persisted to PostgreSQL and attached to the originating run;
- independent GLM Flash verifier stamping GROUNDED / PARTIAL / UNGROUNDED findings;
- fail-open verifier availability but **fail-closed decision eligibility**: UNVERIFIED,
  UNGROUNDED, empty-evidence and unknown-evidence findings cannot reach the final judge;
- deterministic confidence penalty for PARTIAL findings;
- GPT-5.6 Sol final judge selecting a maximum of three interventions;
- application-level evidence validation on judge output so invented evidence IDs are discarded;
- deterministic decision scoring and code-owned final ranking (model-supplied rank cannot override it);
- clean `NEEDS_DATA` completion with zero interventions when no finding clears the evidence gate;
- operator feedback loop: `/feedback <run-prefix> <rank> <VERDICT> [note]` records
  ADOPTED / REJECTED / EXECUTED_VERIFIED / EXECUTED_NO_SIGNAL / PARTIAL verdicts;
- the last 50 operator verdicts and 10 completed runs are injected into future reasoning;
- native OpenAI Responses API + Pydantic Structured Outputs for Luna/Terra/Sol;
- DeepSeek Responses API JSON-Schema adapter for `deepseek-v4-flash`;
- explicit GLM OpenAI-compatible adapter, with no silent provider fallback;
- PostgreSQL/pgvector execution ledger with per-agent latency/token telemetry;
- idempotent Telegram-triggered workflow IDs to prevent duplicate runs on webhook retries;
- final Telegram completion/failure notification;
- strict Pydantic contracts between workflow activities;
- production mutations disabled by default;
- Docker Compose local/VPS stack using Temporal's CLI development server;
- CI with Ruff, strict mypy, pytest and Compose validation.

Intentionally **not** added yet: Redis/Celery, LangGraph, Neo4j, E2B, or autonomous production writes. They are unnecessary until measured evidence proves a need.

## Architecture (v0.3)

```text
Alexios
  |
Telegram (/portfolio, /feedback)
  |
FastAPI gateway
  |
Temporal workflow
  |-- canonical site registry
  |-- GSC read-only evidence collector --> PostgreSQL evidence ledger
  |-- run history + feedback memory + operating rules
  |-- GLM 5.3 diagnostician -------\
  |-- GPT-5.6 Terra strategist -----+--> GLM 5.3 Flash verifier
  `-- GPT-5.6 Luna state triage ----/             |
                                      deterministic grounding gate
                                                   |
                                         GPT-5.6 Sol judge
                                                   |
                                      deterministic score/rank
                                                   |
                                                result
```

DeepSeek V4 Flash remains registered as the implementation engine but deliberately unused in the read-only workflow.

## Safety invariants

1. `READ_ONLY` is the default run mode.
2. `ALLOW_PRODUCTION_WRITES=false` is the default hard gate.
3. Production Telegram requires both a webhook secret and an explicit user allowlist.
4. LLMs never generate database mutation instructions; application code owns persistence.
5. Agent identity/model identity is assigned by the orchestrator, not trusted from model output.
6. Webhook retries are idempotent.
7. There is no hidden model routing or silent fallback.
8. Provider secrets are environment variables/runtime mounts and must never be committed.
9. A finding is judge-eligible only when it is GROUNDED or PARTIAL and every cited evidence ID
   exists in the current run evidence set. PARTIAL confidence is discounted in code.
10. A judge intervention is discarded if it lacks evidence or cites evidence outside the run.

## Local development

```bash
cp .env.example .env
# Fill only the credentials/endpoints you actually use.
docker compose up --build
```

For the existing Hermes service-account cache on a VPS, the worker mounts
`${HOME}/.hermes/cache` read-only at `/run/hermes-cache`. Configure the `.env` with the exact
file or a glob that resolves to exactly one file, for example:

```bash
GSC_SERVICE_ACCOUNT_FILE=/run/hermes-cache/seo-optimizer-456317-*.json
```

If `GSC_SERVICE_ACCOUNT_FILE` is blank or invalid, GSC-dependent reasoning receives no fabricated
fallback data and the workflow can return `NEEDS_DATA`.

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
last 50 verdicts as ground truth about operator preference and past outcomes.

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

After v0.3 is validated and deployed read-only, continue evidence depth in this order:

1. GA4 organic sessions, key events, conversion and revenue evidence;
2. priority-only GSC URL Inspection for URLs selected by Search Analytics evidence;
3. Bing Webmaster data;
4. WordPress read-only inventory, canonical/sitemap/meta/schema state and rendered evidence;
5. GitHub/repository/deployment state;
6. HTTP/Playwright/schema verification;
7. PR-based implementation with explicit approval, rollback, write locks and post-change verification.

Do not enable production writes until approval signals, rollback, write locks, independent verification and post-change measurement are implemented and tested.
