-- Sovereign AI — Routing Percentile Bands Migration
-- Provides statistical distribution of complexity scores per tier for
-- dashboard analysis, threshold validation, and hysteresis tuning.
--
-- Run once:
--   docker cp postgres/migrations/07_routing_percentiles.sql sovereign-postgres:/tmp/
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -f /tmp/07_routing_percentiles.sql
--
-- No schema change required — complexity_score and tier already exist in audit_log.

-- ── Score percentile bands per tier ──────────────────────────────────────────

CREATE OR REPLACE VIEW routing_score_percentiles AS
SELECT
    tier,
    COUNT(*)                                                                      AS request_count,
    ROUND(MIN(complexity_score)::numeric, 1)                                      AS score_min,
    ROUND(percentile_cont(0.10) WITHIN GROUP (ORDER BY complexity_score)::numeric, 1) AS score_p10,
    ROUND(percentile_cont(0.25) WITHIN GROUP (ORDER BY complexity_score)::numeric, 1) AS score_p25,
    ROUND(percentile_cont(0.50) WITHIN GROUP (ORDER BY complexity_score)::numeric, 1) AS score_p50,
    ROUND(percentile_cont(0.75) WITHIN GROUP (ORDER BY complexity_score)::numeric, 1) AS score_p75,
    ROUND(percentile_cont(0.90) WITHIN GROUP (ORDER BY complexity_score)::numeric, 1) AS score_p90,
    ROUND(MAX(complexity_score)::numeric, 1)                                      AS score_max,
    ROUND(AVG(complexity_score)::numeric, 1)                                      AS score_avg,
    ROUND(STDDEV(complexity_score)::numeric, 1)                                   AS score_stddev
FROM audit_log
WHERE complexity_score IS NOT NULL
GROUP BY tier
ORDER BY tier;

COMMENT ON VIEW routing_score_percentiles IS
    'Percentile distribution (P10/P25/P50/P75/P90) of complexity scores per routing tier. '
    'Use to validate threshold placement and calibrate hysteresis buffer size. '
    'If P90 for TIER_1 is close to 20, consider widening the hysteresis buffer.';

-- ── Boundary zone analysis ────────────────────────────────────────────────────
-- Identifies requests that fell inside a hysteresis boundary zone.
-- Hardcoded at thresholds ±2 (default buffer); adjust if ROUTER_HYSTERESIS_BUFFER changes.

CREATE OR REPLACE VIEW routing_boundary_analysis AS
SELECT
    request_id,
    created_at,
    session_id,
    tier,
    ROUND(complexity_score::numeric, 1) AS score,
    CASE
        WHEN complexity_score BETWEEN 18 AND 22 THEN 'T1_T2_boundary'
        WHEN complexity_score BETWEEN 43 AND 47 THEN 'T2_T3_boundary'
    END AS boundary_zone
FROM audit_log
WHERE complexity_score IS NOT NULL
  AND (
        complexity_score BETWEEN 18 AND 22
     OR complexity_score BETWEEN 43 AND 47
  )
ORDER BY created_at DESC;

COMMENT ON VIEW routing_boundary_analysis IS
    'Requests whose complexity score landed inside a hysteresis boundary zone '
    '(±2 of tier threshold). Use to measure how often hysteresis actually fires '
    'and to detect threshold drift over time.';

-- ── Hysteresis effectiveness summary ─────────────────────────────────────────
-- Aggregates boundary-zone traffic by tier to show how often the buffer matters.

CREATE OR REPLACE VIEW routing_hysteresis_summary AS
SELECT
    boundary_zone,
    tier                                    AS routed_tier,
    COUNT(*)                                AS request_count,
    MIN(created_at)                         AS first_seen,
    MAX(created_at)                         AS last_seen
FROM routing_boundary_analysis
GROUP BY boundary_zone, tier
ORDER BY boundary_zone, tier;

COMMENT ON VIEW routing_hysteresis_summary IS
    'Aggregates boundary-zone requests by the tier they were actually routed to. '
    'E.g. if T1_T2_boundary requests are split between TIER_1 and TIER_2, '
    'the hysteresis buffer is doing its job preventing flip-flopping.';

SELECT 'Migration 07_routing_percentiles applied successfully' AS status;
