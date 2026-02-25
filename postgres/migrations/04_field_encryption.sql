-- Sovereign AI — Field Encryption Documentation Marker
-- Phase 3: user_query and response_preview are encrypted at the application
-- layer using Fernet (AES-128-CBC + HMAC-SHA256) when FIELD_ENCRYPTION_KEY
-- is set. Keys are stored in environment variables — never in the database.
-- Legacy plaintext rows remain readable (graceful fallback in AuditCrypto.decrypt).
--
-- Apply once (idempotent — COMMENTs are always safe to re-run):
--   docker exec sovereign-postgres psql -U sovereign -d sovereign_audit \
--     -f /tmp/04_field_encryption.sql
--

COMMENT ON COLUMN audit_log.user_query IS
  'AES-128 encrypted (Fernet) when FIELD_ENCRYPTION_KEY is set. '
  'Plaintext for pre-Phase-3 rows (graceful fallback in application layer).';

COMMENT ON COLUMN audit_log.response_preview IS
  'AES-128 encrypted (Fernet) when FIELD_ENCRYPTION_KEY is set. '
  'Plaintext for pre-Phase-3 rows (graceful fallback in application layer).';

-- ── Verify ─────────────────────────────────────────────────────────────────

SELECT 'Migration 04_field_encryption applied successfully' AS status;

SELECT
  column_name,
  LEFT(col_description(('audit_log')::regclass, ordinal_position), 60) AS comment_preview
FROM information_schema.columns
WHERE table_name = 'audit_log'
  AND column_name IN ('user_query', 'response_preview')
ORDER BY column_name;
