-- Sovereign AI — Model Governance Migration
-- Adds governance_meta JSONB column to audit_log.
-- Populated per-request with ModelFingerprint:
--   config_hash      — SHA256(model names + routing thresholds + temperature)
--   embedding_model  — embedding model name (e.g., "all-MiniLM-L6-v2")
--   prompt_template_hash — SHA256 of the static base system prompt
--   secure_mode      — whether SECURE_MODE was active at time of request
-- Idempotent — safe to re-run.
--
-- Apply:
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit \
--     -f /tmp/05_model_governance.sql

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS governance_meta JSONB;

-- Index on config_hash for efficient drift detection queries
CREATE INDEX IF NOT EXISTS idx_audit_governance_config
    ON audit_log ((governance_meta->>'config_hash'));

-- ── Verify ────────────────────────────────────────────────────────────────────

SELECT 'Migration 05_model_governance applied successfully' AS status;

SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'audit_log' AND column_name = 'governance_meta';
