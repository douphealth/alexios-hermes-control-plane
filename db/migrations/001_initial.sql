CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS runs (
    run_id text PRIMARY KEY,
    objective text NOT NULL,
    mode text NOT NULL,
    status text NOT NULL,
    result_json jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_runs_status_created ON runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS agent_results (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    agent text NOT NULL,
    model text NOT NULL,
    prompt_version text NOT NULL,
    provider_request_id text,
    latency_ms integer,
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    result_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_agent_results_run_id ON agent_results(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_results_agent_created ON agent_results(agent, created_at DESC);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id text PRIMARY KEY,
    run_id text REFERENCES runs(run_id) ON DELETE SET NULL,
    source text NOT NULL,
    summary text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    embedding vector(1536),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_run_id ON evidence(run_id);

CREATE TABLE IF NOT EXISTS approvals (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    scope jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED')),
    approved_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_approvals_run_status ON approvals(run_id, status);
