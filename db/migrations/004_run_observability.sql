ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS run_kind text NOT NULL DEFAULT 'PORTFOLIO',
    ADD COLUMN IF NOT EXISTS phase text NOT NULL DEFAULT 'STARTING',
    ADD COLUMN IF NOT EXISTS phase_detail text,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_runs_kind_status_updated
    ON runs(run_kind, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_runs_updated
    ON runs(updated_at DESC);
