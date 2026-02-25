-- Sovereign AI — Audit Layer Enhancement Migration
-- Run once against the running sovereign_audit database:
--   docker cp postgres/migrations/02_audit_enhancement.sql sovereign-postgres:/tmp/
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -f /tmp/02_audit_enhancement.sql
--
-- All statements are idempotent (ADD COLUMN IF NOT EXISTS).

-- ── Enhanced audit_log columns ────────────────────────────────────────────────

ALTER TABLE audit_log
    ADD COLUMN IF NOT EXISTS session_id                    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS client_ip                     VARCHAR(45),
    ADD COLUMN IF NOT EXISTS query_hash                    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS mode                          VARCHAR(20) DEFAULT 'connected',
    ADD COLUMN IF NOT EXISTS retrieval_audit               JSONB,
    ADD COLUMN IF NOT EXISTS eligibility_detail            JSONB,
    ADD COLUMN IF NOT EXISTS policy_snapshot               JSONB,
    ADD COLUMN IF NOT EXISTS hallucination_guard_triggered BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS input_tokens                  INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS output_tokens                 INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS llm_stop_reason               VARCHAR(20),
    ADD COLUMN IF NOT EXISTS refusal_flag                  BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS citation_present              BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS temperature                   REAL,
    ADD COLUMN IF NOT EXISTS error_detail                  TEXT,
    ADD COLUMN IF NOT EXISTS entry_hash                    VARCHAR(64),
    ADD COLUMN IF NOT EXISTS previous_hash                 VARCHAR(64);

-- ── New indexes ───────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_audit_query_hash ON audit_log (query_hash);
CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_log (session_id);

-- ── Security events table (new) ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS security_events (
    id              BIGSERIAL PRIMARY KEY,
    request_id      UUID NOT NULL,
    detected_at     TIMESTAMPTZ DEFAULT NOW(),
    event_type      VARCHAR(50) NOT NULL,
    severity        VARCHAR(10) NOT NULL,
    pattern_matched TEXT,
    query_fragment  VARCHAR(200),
    entry_hash      VARCHAR(64),
    previous_hash   VARCHAR(64)
);

CREATE INDEX IF NOT EXISTS idx_sec_request_id  ON security_events (request_id);
CREATE INDEX IF NOT EXISTS idx_sec_detected_at ON security_events (detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_sec_severity    ON security_events (severity);

-- ── Updated views ─────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW routing_stats AS
SELECT
    date_trunc('hour', created_at)                          AS hour,
    tier,
    COUNT(*)                                                AS requests,
    ROUND(AVG(complexity_score)::numeric, 2)                AS avg_score,
    ROUND(AVG(latency_ms)::numeric, 0)                      AS avg_latency_ms,
    ROUND(AVG(input_tokens)::numeric, 0)                    AS avg_input_tokens,
    ROUND(AVG(output_tokens)::numeric, 0)                   AS avg_output_tokens,
    COUNT(CASE WHEN eligibility_outcome = TRUE  THEN 1 END) AS eligible_count,
    COUNT(CASE WHEN eligibility_outcome = FALSE THEN 1 END) AS ineligible_count,
    COUNT(CASE WHEN hallucination_guard_triggered THEN 1 END) AS guard_triggers,
    COUNT(CASE WHEN refusal_flag     THEN 1 END)            AS refusals,
    COUNT(CASE WHEN citation_present THEN 1 END)            AS cited_responses
FROM audit_log
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

CREATE OR REPLACE VIEW security_event_summary AS
SELECT
    date_trunc('hour', detected_at) AS hour,
    event_type,
    severity,
    COUNT(*)                        AS occurrences
FROM security_events
WHERE detected_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC;

CREATE OR REPLACE VIEW daily_summary AS
SELECT
    date_trunc('day', created_at)                           AS day,
    COUNT(*)                                                AS total_requests,
    COUNT(DISTINCT benefit_id)                              AS benefits_queried,
    COUNT(CASE WHEN tier = 'TIER_1' THEN 1 END)            AS tier1_count,
    COUNT(CASE WHEN tier = 'TIER_2' THEN 1 END)            AS tier2_count,
    COUNT(CASE WHEN tier = 'TIER_3' THEN 1 END)            AS tier3_count,
    COUNT(CASE WHEN eligibility_outcome = TRUE  THEN 1 END) AS eligible_count,
    COUNT(CASE WHEN eligibility_outcome = FALSE THEN 1 END) AS ineligible_count,
    ROUND(AVG(latency_ms)::numeric, 0)                     AS avg_latency_ms,
    SUM(input_tokens)                                       AS total_input_tokens,
    SUM(output_tokens)                                      AS total_output_tokens,
    COUNT(CASE WHEN hallucination_guard_triggered THEN 1 END) AS guard_triggers,
    COUNT(CASE WHEN refusal_flag     THEN 1 END)            AS refusals,
    COUNT(CASE WHEN citation_present THEN 1 END)            AS cited_responses
FROM audit_log
GROUP BY 1
ORDER BY 1 DESC;

-- ── Verify ────────────────────────────────────────────────────────────────────

SELECT 'Migration 02_audit_enhancement applied successfully' AS status;
SELECT column_name FROM information_schema.columns
WHERE table_name = 'audit_log' AND column_name IN
  ('session_id', 'client_ip', 'query_hash', 'entry_hash', 'retrieval_audit',
   'eligibility_detail', 'input_tokens', 'hallucination_guard_triggered')
ORDER BY column_name;
