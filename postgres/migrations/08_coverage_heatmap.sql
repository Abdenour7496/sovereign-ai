-- Sovereign AI — Eligibility Coverage Heatmap Migration
-- SQL views for eligibility coverage observability:
--   1. eligibility_weekly_heatmap     — weekly × benefit evaluation breakdown
--   2. eligibility_condition_summary  — per-condition pass/fail/missing/unknown stats
--   3. eligibility_missing_fields_summary — which applicant fields are most often absent
--
-- Run once:
--   docker cp postgres/migrations/08_coverage_heatmap.sql sovereign-postgres:/tmp/
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit -f /tmp/08_coverage_heatmap.sql
--
-- No schema changes required — all views read from existing audit_log JSONB columns.

-- ── Weekly evaluation heatmap ─────────────────────────────────────────────────
-- Groups eligibility queries by calendar week × benefit_id.
-- Separates: eligible / ineligible (rule failed) / incomplete (missing applicant data) / no_rules.

CREATE OR REPLACE VIEW eligibility_weekly_heatmap AS
SELECT
    date_trunc('week', created_at)                                          AS week,
    benefit_id,
    COUNT(*)                                                                AS total_queries,
    COUNT(*) FILTER (WHERE eligibility_outcome IS NOT NULL)                 AS evaluations_run,
    COUNT(*) FILTER (WHERE eligibility_outcome = true)                      AS eligible_count,
    COUNT(*) FILTER (
        WHERE eligibility_outcome = false
          AND jsonb_array_length(
                COALESCE(eligibility_detail->'missing_information', '[]'::jsonb)
              ) = 0
    )                                                                       AS ineligible_count,
    COUNT(*) FILTER (
        WHERE eligibility_outcome = false
          AND jsonb_array_length(
                COALESCE(eligibility_detail->'missing_information', '[]'::jsonb)
              ) > 0
    )                                                                       AS incomplete_data_count,
    COUNT(*) FILTER (
        WHERE (eligibility_detail->>'no_rules')::boolean = true
    )                                                                       AS no_rules_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE eligibility_outcome IS NOT NULL)
        / NULLIF(COUNT(*), 0),
    1)                                                                      AS evaluation_coverage_pct
FROM audit_log
WHERE benefit_id IS NOT NULL
  AND intent_type = 'eligibility_query'
GROUP BY week, benefit_id
ORDER BY week DESC, benefit_id;

COMMENT ON VIEW eligibility_weekly_heatmap IS
    'Weekly × benefit eligibility evaluation breakdown. '
    'evaluation_coverage_pct < 100 means some queries had no deterministic result. '
    'no_rules_count > 0 means benefit exists in graph without evaluable rules. '
    'Use as a Grafana time-series heatmap datasource.';

-- ── Per-condition evaluation statistics ──────────────────────────────────────
-- Unpacks eligibility_detail->condition_results JSONB to get per-condition stats.
-- Shows which conditions are always passing, always failing, or chronically missing data.

CREATE OR REPLACE VIEW eligibility_condition_summary AS
SELECT
    a.benefit_id,
    cond_result->>'rule'                                    AS rule_name,
    cond_detail->>'field'                                   AS field,
    cond_detail->>'condition'                               AS condition_name,
    COUNT(*)                                                AS times_evaluated,
    COUNT(*) FILTER (WHERE cond_detail->>'status' = 'passed')           AS passed_count,
    COUNT(*) FILTER (WHERE cond_detail->>'status' = 'failed')           AS failed_count,
    COUNT(*) FILTER (WHERE cond_detail->>'status' = 'missing_data')     AS missing_count,
    COUNT(*) FILTER (WHERE cond_detail->>'status' = 'unknown_operator') AS unknown_op_count,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE cond_detail->>'status' = 'passed')
        / NULLIF(COUNT(*), 0),
    1)                                                      AS pass_rate_pct,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE cond_detail->>'status' = 'missing_data')
        / NULLIF(COUNT(*), 0),
    1)                                                      AS missing_rate_pct
FROM audit_log a,
     jsonb_array_elements(a.eligibility_detail->'condition_results') AS cond_result,
     jsonb_array_elements(cond_result->'conditions')                  AS cond_detail
WHERE a.eligibility_detail IS NOT NULL
  AND a.benefit_id IS NOT NULL
GROUP BY a.benefit_id, rule_name, field, condition_name
ORDER BY a.benefit_id, rule_name, field;

COMMENT ON VIEW eligibility_condition_summary IS
    'Per-condition evaluation statistics unpacked from eligibility_detail JSONB. '
    'missing_rate_pct high → citizens often lack this data; consider adding a prompt. '
    'unknown_op_count > 0 → policy graph uses an operator the engine does not support. '
    'pass_rate_pct = 100 → condition may never block eligibility; review if intentional.';

-- ── Missing field frequency ───────────────────────────────────────────────────
-- Which applicant fields are most commonly absent during eligibility evaluation.
-- High counts indicate gaps in the citizen-facing data collection UX.

CREATE OR REPLACE VIEW eligibility_missing_fields_summary AS
SELECT
    a.benefit_id,
    cond_detail->>'field'                                   AS missing_field,
    COUNT(*)                                                AS occurrences,
    ROUND(
        100.0 * COUNT(*)
        / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY a.benefit_id), 0),
    1)                                                      AS pct_of_benefit_missing,
    MIN(a.created_at)                                       AS first_seen,
    MAX(a.created_at)                                       AS last_seen
FROM audit_log a,
     jsonb_array_elements(a.eligibility_detail->'condition_results') AS cond_result,
     jsonb_array_elements(cond_result->'conditions')                  AS cond_detail
WHERE a.eligibility_detail IS NOT NULL
  AND a.benefit_id IS NOT NULL
  AND cond_detail->>'status' = 'missing_data'
GROUP BY a.benefit_id, missing_field
ORDER BY a.benefit_id, occurrences DESC;

COMMENT ON VIEW eligibility_missing_fields_summary IS
    'Most frequently missing applicant fields per benefit. '
    'High occurrences mean citizens are not providing this data in their queries. '
    'Use to prioritise which fields to prompt for in the citizen-facing UX.';

-- ── Unknown operator audit ────────────────────────────────────────────────────
-- Identifies requests where the engine encountered an unsupported operator.
-- These silently fail: the condition evaluates to False and may wrongly deny eligibility.

CREATE OR REPLACE VIEW eligibility_unknown_operator_log AS
SELECT
    a.request_id,
    a.created_at,
    a.benefit_id,
    jsonb_array_elements_text(a.eligibility_detail->'unknown_operators') AS unknown_operator
FROM audit_log a
WHERE a.eligibility_detail IS NOT NULL
  AND jsonb_array_length(
        COALESCE(a.eligibility_detail->'unknown_operators', '[]'::jsonb)
      ) > 0
ORDER BY a.created_at DESC;

COMMENT ON VIEW eligibility_unknown_operator_log IS
    'All requests where eligibility evaluation encountered an unknown operator. '
    'Each row = one request where at least one condition could not be evaluated. '
    'Requires either adding the operator to EligibilityEngine.OPERATORS or '
    'updating the policy graph to use a supported operator.';

-- ── Indexes for JSONB queries ─────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_audit_intent_type
    ON audit_log (intent_type);

CREATE INDEX IF NOT EXISTS idx_audit_benefit_intent
    ON audit_log (benefit_id, intent_type);

CREATE INDEX IF NOT EXISTS idx_audit_eligibility_outcome
    ON audit_log (eligibility_outcome)
    WHERE eligibility_outcome IS NOT NULL;

SELECT 'Migration 08_coverage_heatmap applied successfully' AS status;
