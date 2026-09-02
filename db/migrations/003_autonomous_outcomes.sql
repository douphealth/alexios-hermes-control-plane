CREATE TABLE IF NOT EXISTS autonomous_mutations (
    mutation_id text PRIMARY KEY,
    workflow_id text NOT NULL,
    site_id text NOT NULL,
    target_url text NOT NULL,
    post_id bigint NOT NULL,
    mutation_type text NOT NULL,
    status text NOT NULL,
    evidence_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    before_sha256 text NOT NULL,
    after_sha256 text,
    backup_path text,
    baseline_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    applied_at timestamptz NOT NULL DEFAULT now(),
    rolled_back boolean NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS autonomous_mutations_site_applied_idx
    ON autonomous_mutations(site_id, applied_at DESC);

CREATE TABLE IF NOT EXISTS autonomous_measurements (
    id bigserial PRIMARY KEY,
    mutation_id text NOT NULL REFERENCES autonomous_mutations(mutation_id) ON DELETE CASCADE,
    window_days integer NOT NULL CHECK (window_days IN (7,14,28)),
    measured_at timestamptz NOT NULL DEFAULT now(),
    period_start date NOT NULL,
    period_end date NOT NULL,
    clicks double precision NOT NULL DEFAULT 0,
    impressions double precision NOT NULL DEFAULT 0,
    ctr double precision NOT NULL DEFAULT 0,
    position double precision NOT NULL DEFAULT 0,
    baseline_clicks double precision NOT NULL DEFAULT 0,
    baseline_impressions double precision NOT NULL DEFAULT 0,
    baseline_ctr double precision NOT NULL DEFAULT 0,
    baseline_position double precision NOT NULL DEFAULT 0,
    delta_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(mutation_id, window_days)
);

CREATE INDEX IF NOT EXISTS autonomous_measurements_mutation_window_idx
    ON autonomous_measurements(mutation_id, window_days);
