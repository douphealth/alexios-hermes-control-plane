ALTER TABLE evidence ADD COLUMN IF NOT EXISTS site_id text;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS kind text;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS observed_at timestamptz;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS period_start date;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS period_end date;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS source_property text;
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS payload_hash text;

CREATE INDEX IF NOT EXISTS idx_evidence_site_kind_observed
    ON evidence(site_id, kind, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_payload_hash
    ON evidence(payload_hash);
