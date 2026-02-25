-- Sovereign AI — Policy Fingerprint Migration
-- Exposes the five-dimension governance_meta JSONB as queryable SQL columns.
--
-- Run once:
--   docker cp postgres/migrations/06_policy_fingerprint.sql sovereign-postgres:/tmp/
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -f /tmp/06_policy_fingerprint.sql
--
-- No schema change is required — governance_meta JSONB already exists.
-- This migration adds a VIEW for replay verification queries and an index
-- on policy_graph_hash for cross-request graph version analysis.

-- ── Extracted governance_meta view ────────────────────────────────────────────

CREATE OR REPLACE VIEW governance_fingerprint_log AS
SELECT
    request_id,
    created_at,
    tier,
    benefit_id,
    -- 1. Model config
    governance_meta->>'config_hash'           AS config_hash,
    governance_meta->>'embedding_model'       AS embedding_model,
    governance_meta->>'prompt_template_hash'  AS prompt_template_hash,
    (governance_meta->>'secure_mode')::boolean AS secure_mode,
    -- 2. Source integrity
    governance_meta->>'engine_source_hash'    AS engine_source_hash,
    governance_meta->>'router_source_hash'    AS router_source_hash,
    -- 3. Policy graph
    governance_meta->>'policy_graph_hash'     AS policy_graph_hash,
    (governance_meta->>'policy_graph_node_count')::int AS policy_graph_node_count,
    -- 4. Router thresholds
    governance_meta->'router_thresholds'      AS router_thresholds,
    -- 5. Temporal anchor
    governance_meta->>'startup_at'            AS startup_at,
    governance_meta->'config_snapshot'        AS config_snapshot
FROM audit_log
WHERE governance_meta IS NOT NULL;

COMMENT ON VIEW governance_fingerprint_log IS
    'Five-dimension system fingerprint extracted from governance_meta JSONB. '
    'Use for replay verification: group by policy_graph_hash to identify all '
    'requests made against the same policy graph version, or by config_hash '
    'to identify requests made with the same model configuration.';

-- ── Index for policy graph version queries ────────────────────────────────────
-- Allows: SELECT * FROM audit_log WHERE governance_meta->>'policy_graph_hash' = '<hash>'

CREATE INDEX IF NOT EXISTS idx_audit_policy_graph_hash
    ON audit_log ((governance_meta->>'policy_graph_hash'));

CREATE INDEX IF NOT EXISTS idx_audit_config_hash
    ON audit_log ((governance_meta->>'config_hash'));

CREATE INDEX IF NOT EXISTS idx_audit_engine_source_hash
    ON audit_log ((governance_meta->>'engine_source_hash'));

-- ── Replay completeness summary ───────────────────────────────────────────────

CREATE OR REPLACE VIEW replay_completeness_summary AS
SELECT
    governance_meta->>'config_hash'          AS config_hash,
    governance_meta->>'engine_source_hash'   AS engine_source_hash,
    governance_meta->>'router_source_hash'   AS router_source_hash,
    governance_meta->>'policy_graph_hash'    AS policy_graph_hash,
    governance_meta->>'startup_at'           AS startup_at,
    COUNT(*)                                 AS request_count,
    MIN(created_at)                          AS first_request,
    MAX(created_at)                          AS last_request,
    BOOL_AND(governance_meta->>'policy_graph_hash' IS NOT NULL) AS replay_complete
FROM audit_log
WHERE governance_meta IS NOT NULL
GROUP BY 1, 2, 3, 4, 5
ORDER BY first_request DESC;

COMMENT ON VIEW replay_completeness_summary IS
    'Groups audit log entries by their full five-dimension fingerprint. '
    'replay_complete=true means all five dimensions were captured. '
    'Each distinct row represents a unique deployment configuration. '
    'Use to verify that policy graph changes are reflected in new fingerprint rows.';

SELECT 'Migration 06_policy_fingerprint applied successfully' AS status;
