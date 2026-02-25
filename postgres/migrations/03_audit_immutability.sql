-- Sovereign AI — Audit Immutability Migration
-- Enforces append-only behaviour on both audit tables and creates
-- least-privilege DB roles for production connection separation.
--
-- Apply once against the running sovereign_audit database:
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit \
--     -f /tmp/03_audit_immutability.sql
--
-- All statements are idempotent.

-- ── Immutability trigger function ─────────────────────────────────────────────
-- A single function shared by both audit tables.
-- Fires BEFORE UPDATE OR DELETE — raises an exception that rolls back the
-- offending statement for every caller, including superusers.

CREATE OR REPLACE FUNCTION fn_audit_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION
    'Sovereign audit table is append-only: % on "%" is prohibited. '
    'Chain integrity would be violated.',
    TG_OP, TG_TABLE_NAME;
END;
$$;

-- ── audit_log trigger ─────────────────────────────────────────────────────────

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.triggers
    WHERE trigger_name = 'trg_audit_log_immutable'
      AND event_object_table = 'audit_log'
  ) THEN
    CREATE TRIGGER trg_audit_log_immutable
      BEFORE UPDATE OR DELETE ON audit_log
      FOR EACH ROW EXECUTE FUNCTION fn_audit_immutable();
  END IF;
END $$;

-- ── security_events trigger ───────────────────────────────────────────────────

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.triggers
    WHERE trigger_name = 'trg_security_events_immutable'
      AND event_object_table = 'security_events'
  ) THEN
    CREATE TRIGGER trg_security_events_immutable
      BEFORE UPDATE OR DELETE ON security_events
      FOR EACH ROW EXECUTE FUNCTION fn_audit_immutable();
  END IF;
END $$;

-- ── Least-privilege roles ─────────────────────────────────────────────────────
-- These roles are created for production connection separation.
-- The application should connect as sovereign_writer (not as the superuser).
-- Rotate passwords before deploying to production.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sovereign_writer') THEN
    CREATE ROLE sovereign_writer WITH LOGIN PASSWORD 'CHANGE_BEFORE_PRODUCTION';
  END IF;
END $$;

GRANT CONNECT ON DATABASE sovereign_audit TO sovereign_writer;
GRANT USAGE ON SCHEMA public TO sovereign_writer;
-- INSERT only — triggers already prevent UPDATE/DELETE
GRANT INSERT ON audit_log, security_events TO sovereign_writer;
GRANT USAGE ON SEQUENCE audit_log_id_seq, security_events_id_seq TO sovereign_writer;
-- Minimal SELECT for hash-chain lookups (previous hash + id ordering)
GRANT SELECT (id, entry_hash) ON audit_log TO sovereign_writer;
GRANT SELECT (id, entry_hash) ON security_events TO sovereign_writer;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sovereign_auditor') THEN
    CREATE ROLE sovereign_auditor WITH LOGIN PASSWORD 'CHANGE_BEFORE_PRODUCTION';
  END IF;
END $$;

GRANT CONNECT ON DATABASE sovereign_audit TO sovereign_auditor;
GRANT USAGE ON SCHEMA public TO sovereign_auditor;
GRANT SELECT ON audit_log, security_events TO sovereign_auditor;
GRANT SELECT ON routing_stats, security_event_summary, daily_summary TO sovereign_auditor;

-- ── Verify ────────────────────────────────────────────────────────────────────

SELECT 'Migration 03_audit_immutability applied successfully' AS status;

SELECT trigger_name, event_object_table AS table_name
FROM information_schema.triggers
WHERE trigger_name IN ('trg_audit_log_immutable', 'trg_security_events_immutable')
ORDER BY table_name;

SELECT rolname FROM pg_roles
WHERE rolname IN ('sovereign_writer', 'sovereign_auditor')
ORDER BY rolname;
