-- Operator feedback loop: verdicts on past interventions.
-- This is what makes prompts compound: verdicts are injected into future runs.

CREATE TABLE IF NOT EXISTS intervention_feedback (
    id bigserial PRIMARY KEY,
    run_id text NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    intervention_rank int NOT NULL CHECK (intervention_rank BETWEEN 1 AND 3),
    verdict text NOT NULL CHECK (verdict IN (
        'ADOPTED',
        'REJECTED',
        'EXECUTED_VERIFIED',
        'EXECUTED_NO_SIGNAL',
        'PARTIAL'
    )),
    outcome_note text,
    metrics_delta jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_run ON intervention_feedback(run_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON intervention_feedback(created_at DESC);
