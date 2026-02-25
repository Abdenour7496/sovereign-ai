-- Sovereign AI — Postgres Audit Schema (Sovereign Runtime Audit Layer)
-- Created on first startup via docker-entrypoint-initdb.d
-- audit/logger.py also calls ensure_schema() for idempotent bootstrap.

-- ── Main audit log (tamper-evident, hash-chained) ─────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
    id                            BIGSERIAL PRIMARY KEY,
    request_id                    UUID NOT NULL,
    session_id                    VARCHAR(64),
    client_ip                     VARCHAR(45),
    user_query                    TEXT,
    query_hash                    VARCHAR(64),
    mode                          VARCHAR(20) DEFAULT 'connected',
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    complexity_score              REAL,
    tier                          VARCHAR(16),
    llm_model                     VARCHAR(64),
    intent_type                   VARCHAR(64),
    benefit_id                    VARCHAR(64),
    neo4j_nodes                   JSONB DEFAULT '[]',
    retrieval_audit               JSONB,
    eligibility_outcome           BOOLEAN,
    eligibility_detail            JSONB,
    policy_snapshot               JSONB,
    hallucination_guard_triggered BOOLEAN DEFAULT FALSE,
    input_tokens                  INTEGER DEFAULT 0,
    output_tokens                 INTEGER DEFAULT 0,
    llm_stop_reason               VARCHAR(20),
    refusal_flag                  BOOLEAN DEFAULT FALSE,
    citation_present              BOOLEAN DEFAULT FALSE,
    temperature                   REAL,
    response_preview              TEXT,
    latency_ms                    INTEGER,
    error_detail                  TEXT,
    entry_hash                    VARCHAR(64),
    previous_hash                 VARCHAR(64),
    CONSTRAINT audit_log_request_id_unique UNIQUE (request_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_benefit_id ON audit_log (benefit_id);
CREATE INDEX IF NOT EXISTS idx_audit_tier       ON audit_log (tier);
CREATE INDEX IF NOT EXISTS idx_audit_query_hash ON audit_log (query_hash);
CREATE INDEX IF NOT EXISTS idx_audit_session_id ON audit_log (session_id);

-- ── Security events (separate hash chain) ─────────────────────────────────────

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

-- ── Views ─────────────────────────────────────────────────────────────────────

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

-- ── Dual-Control Classified Replay ────────────────────────────────────────────
-- Two-person integrity tokens for classified security event replay.
-- Managed by audit/dual_control.py; tables created here for fresh deployments.

CREATE TABLE IF NOT EXISTS replay_tokens (
    id                   BIGSERIAL PRIMARY KEY,
    security_event_id    BIGINT NOT NULL,
    token                VARCHAR(64) NOT NULL UNIQUE,
    requested_by_role    VARCHAR(50) NOT NULL,
    requesting_key_hash  VARCHAR(64) NOT NULL,
    reason               TEXT,
    requested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_by_role     VARCHAR(50),
    approved_at          TIMESTAMPTZ,
    status               VARCHAR(20) NOT NULL DEFAULT 'pending',
    expires_at           TIMESTAMPTZ NOT NULL,
    used_at              TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_replay_tokens_token ON replay_tokens(token);
CREATE INDEX IF NOT EXISTS idx_replay_tokens_event ON replay_tokens(security_event_id, status);

-- ── Hash Chain Anchors ────────────────────────────────────────────────────────
-- Periodic snapshots of chain tail hashes with optional RFC 3161 TSA witness.
-- Managed by audit/chain_anchor.py.

CREATE TABLE IF NOT EXISTS chain_anchors (
    id                    BIGSERIAL PRIMARY KEY,
    anchored_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    main_chain_hash       VARCHAR(64),
    main_chain_length     BIGINT NOT NULL DEFAULT 0,
    security_chain_hash   VARCHAR(64),
    security_chain_length BIGINT NOT NULL DEFAULT 0,
    anchor_hash           VARCHAR(64) NOT NULL,
    anchor_type           VARCHAR(20) NOT NULL DEFAULT 'offline',
    external_reference    TEXT,
    tsa_url               VARCHAR(255)
);
CREATE INDEX IF NOT EXISTS idx_chain_anchors_at ON chain_anchors(anchored_at DESC);
