"""
Sovereign Brain — Sovereign Runtime Audit Logger
=================================================
Guarantees:
  1. Every interaction is traceable (session_id, client_ip, query_hash)
  2. Every retrieval step is explainable (retrieval_audit JSONB)
  3. Every authorization decision is recorded (eligibility_detail JSONB)
  4. Logs are tamper-evident (SHA256 hash chaining)
  5. Auditors can reconstruct any answer (replay endpoint)
  6. Security events are logged separately with their own hash chain

Design:
  - Append-only: ON CONFLICT DO NOTHING prevents re-insertion
  - Hash chain: entry_hash = SHA256(canonical_json(entry) + previous_hash)
  - Genesis constant: previous_hash = "SOVEREIGN_GENESIS_0000"
  - Security events: independent hash chain in security_events table
  - All JSONB fields: structured, not text blobs
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import asyncpg

from audit.crypto import AuditCrypto

log = logging.getLogger("sovereign.audit")

GENESIS_HASH = "SOVEREIGN_GENESIS_0000"


def _decrypt_entry(crypto: AuditCrypto, entry: dict) -> dict:
    """Decrypt sensitive fields in an audit log entry dict."""
    for field in ("user_query", "response_preview"):
        if entry.get(field):
            entry[field] = crypto.decrypt(entry[field])
    return entry


class AuditLogger:
    """
    Sovereign-grade audit logger with hash chaining and security event tracking.
    Every log write is immutable and chained to the previous entry.
    """

    def __init__(self, settings):
        self.settings = settings
        self._pool: Optional[asyncpg.Pool] = None
        self._crypto = AuditCrypto(settings.field_encryption_key)

    async def connect(self):
        """Initialize connection pool and ensure schema is up to date."""
        try:
            self._pool = await asyncpg.create_pool(
                self.settings.postgres_dsn,
                min_size=1,
                max_size=5,
            )
            await self.ensure_schema()
            log.info("Audit logger connected")
        except Exception as e:
            log.error(f"Audit logger connection failed: {e}")
            self._pool = None

    async def ensure_schema(self):
        """Create tables if they don't exist (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)

    # ── Main Audit Log ────────────────────────────────────────────────────────

    async def log(
        self,
        *,
        request_id: str,
        session_id: str,
        client_ip: str,
        user_query: str,
        query_hash: str,
        mode: str = "connected",
        complexity_score: float,
        tier: str,
        llm_model: str,
        intent_type: Optional[str],
        benefit_id: Optional[str],
        neo4j_nodes: list,
        retrieval_audit: Optional[dict],
        eligibility_outcome: Optional[bool],
        eligibility_detail: Optional[dict],
        policy_snapshot: Optional[list],
        hallucination_guard_triggered: bool,
        input_tokens: int,
        output_tokens: int,
        llm_stop_reason: str,
        refusal_flag: bool,
        citation_present: bool,
        temperature: float,
        response_preview: str,
        latency_ms: int,
        error_detail: Optional[str],
        governance_meta: Optional[dict],
        security_events: Optional[list],
    ):
        """
        Write a fully-structured, hash-chained audit log entry.
        All fields are required for sovereign compliance — use None for unavailable ones.
        """
        if not self._pool:
            log.warning("Audit logger not connected — skipping audit entry")
            return

        # Build the canonical entry for hashing (deterministic fields only).
        # Float fields are rounded to 4dp to survive REAL (float32) round-trip in Postgres.
        entry_data = {
            "request_id": str(request_id),
            "session_id": session_id or "",
            "client_ip": client_ip or "",
            "query_hash": query_hash or "",
            "mode": mode or "connected",
            "complexity_score": round(float(complexity_score or 0), 4),
            "tier": tier or "",
            "llm_model": llm_model or "",
            "intent_type": intent_type,
            "benefit_id": benefit_id,
            "input_tokens": int(input_tokens or 0),
            "output_tokens": int(output_tokens or 0),
            "llm_stop_reason": llm_stop_reason or "",
            "refusal_flag": bool(refusal_flag),
            "citation_present": bool(citation_present),
            "temperature": round(float(temperature or 0), 4),
            "eligibility_outcome": eligibility_outcome,
            "hallucination_guard_triggered": bool(hallucination_guard_triggered),
            "latency_ms": int(latency_ms or 0),
        }

        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1 FOR UPDATE SKIP LOCKED"
                    )
                    previous_hash = (row["entry_hash"] if row and row["entry_hash"] else GENESIS_HASH)
                    entry_hash = _compute_hash(entry_data, previous_hash)

                    await conn.execute(
                        _INSERT_AUDIT_SQL,
                        str(request_id),
                        session_id,
                        client_ip,
                        self._crypto.encrypt(user_query[:2000]) if user_query else "",
                        query_hash,
                        mode,
                        float(complexity_score or 0),
                        tier,
                        llm_model,
                        intent_type,
                        benefit_id,
                        _json(neo4j_nodes),
                        _json(retrieval_audit),
                        eligibility_outcome,
                        _json(eligibility_detail),
                        _json(policy_snapshot),
                        bool(hallucination_guard_triggered),
                        int(input_tokens or 0),
                        int(output_tokens or 0),
                        llm_stop_reason,
                        bool(refusal_flag),
                        bool(citation_present),
                        float(temperature or 0),
                        self._crypto.encrypt(response_preview[:500]) if response_preview else "",
                        int(latency_ms or 0),
                        error_detail,
                        _json(governance_meta),
                        entry_hash,
                        previous_hash,
                    )

            # Log security events (separate chain)
            if security_events:
                await self._log_security_events(str(request_id), security_events)

        except Exception as e:
            log.error(f"Audit log write failed: {e}")

    # ── Security Events ───────────────────────────────────────────────────────

    async def _log_security_events(self, request_id: str, events: list):
        """Log security events with their own independent hash chain."""
        if not self._pool or not events:
            return

        try:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    for event in events:
                        row = await conn.fetchrow(
                            "SELECT entry_hash FROM security_events "
                            "ORDER BY id DESC LIMIT 1 FOR UPDATE SKIP LOCKED"
                        )
                        previous_hash = (row["entry_hash"] if row and row["entry_hash"] else GENESIS_HASH)

                        event_data = {
                            "request_id": request_id,
                            "event_type": event.event_type,
                            "severity": event.severity,
                            "pattern_matched": event.pattern_matched,
                            "query_fragment": event.query_fragment,
                        }
                        entry_hash = _compute_hash(event_data, previous_hash)

                        await conn.execute(
                            _INSERT_SECURITY_EVENT_SQL,
                            request_id,
                            event.event_type,
                            event.severity,
                            event.pattern_matched,
                            event.query_fragment,
                            entry_hash,
                            previous_hash,
                        )
        except Exception as e:
            log.error(f"Security event log write failed: {e}")

    # ── Chain Verification ────────────────────────────────────────────────────

    async def verify_chain(self, limit: int = 1000) -> dict:
        """Walk audit_log entries in insertion order and recompute each hash."""
        if not self._pool:
            return {"valid": False, "error": "not_connected"}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, request_id, entry_hash, previous_hash, created_at,
                       session_id, client_ip, query_hash, mode,
                       complexity_score, tier, llm_model, intent_type,
                       benefit_id, input_tokens, output_tokens, llm_stop_reason,
                       refusal_flag, citation_present, temperature,
                       eligibility_outcome, hallucination_guard_triggered, latency_ms
                FROM audit_log
                ORDER BY id ASC
                LIMIT $1
                """,
                limit,
            )

        if not rows:
            return {
                "valid": True,
                "chain_length": 0,
                "entries_checked": 0,
                "message": "No entries yet",
            }

        # Skip pre-migration entries that have no entry_hash (NULL)
        hashed_rows = [r for r in rows if r["entry_hash"]]
        if not hashed_rows:
            return {
                "valid": True,
                "chain_length": len(rows),
                "entries_checked": 0,
                "pre_migration_entries": len(rows),
                "message": "No hashed entries yet — pre-migration rows skipped",
            }

        broken_at = None
        prev_hash = GENESIS_HASH

        for row in hashed_rows:
            # For the first hashed row, use its stored previous_hash as the chain start
            if prev_hash == GENESIS_HASH and row["previous_hash"]:
                prev_hash = row["previous_hash"]

            entry_data = {
                "request_id": str(row["request_id"]),
                "session_id": row["session_id"] or "",
                "client_ip": row["client_ip"] or "",
                "query_hash": row["query_hash"] or "",
                "mode": row["mode"] or "connected",
                "complexity_score": round(float(row["complexity_score"] or 0), 4),
                "tier": row["tier"] or "",
                "llm_model": row["llm_model"] or "",
                "intent_type": row["intent_type"],
                "benefit_id": row["benefit_id"],
                "input_tokens": int(row["input_tokens"] or 0),
                "output_tokens": int(row["output_tokens"] or 0),
                "llm_stop_reason": row["llm_stop_reason"] or "",
                "refusal_flag": bool(row["refusal_flag"]),
                "citation_present": bool(row["citation_present"]),
                "temperature": round(float(row["temperature"] or 0), 4),
                "eligibility_outcome": row["eligibility_outcome"],
                "hallucination_guard_triggered": bool(row["hallucination_guard_triggered"]),
                "latency_ms": int(row["latency_ms"] or 0),
            }
            expected = _compute_hash(entry_data, prev_hash)

            if expected != row["entry_hash"]:
                broken_at = row["id"]
                break

            prev_hash = row["entry_hash"]

        first_created = hashed_rows[0]["created_at"] if hashed_rows else None
        chain_age = (
            (datetime.now(timezone.utc) - first_created).days
            if first_created else 0
        )

        return {
            "valid": broken_at is None,
            "chain_length": len(rows),
            "entries_checked": len(hashed_rows),
            "pre_migration_entries": len(rows) - len(hashed_rows),
            "first_entry_hash": hashed_rows[0]["entry_hash"] if hashed_rows else None,
            "last_hash": prev_hash,
            "chain_age_days": chain_age,
            "broken_at_id": broken_at,
        }

    async def verify_security_chain(self, limit: int = 500) -> dict:
        """Verify the security_events hash chain."""
        if not self._pool:
            return {"valid": False, "error": "not_connected"}

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, request_id, event_type, severity,
                       pattern_matched, query_fragment, entry_hash
                FROM security_events
                ORDER BY id ASC
                LIMIT $1
                """,
                limit,
            )

        if not rows:
            return {"valid": True, "entries_checked": 0}

        broken_at = None
        prev_hash = GENESIS_HASH

        for row in rows:
            event_data = {
                "request_id": str(row["request_id"]),
                "event_type": row["event_type"],
                "severity": row["severity"],
                "pattern_matched": row["pattern_matched"] or "",
                "query_fragment": row["query_fragment"] or "",
            }
            expected = _compute_hash(event_data, prev_hash)
            if expected != row["entry_hash"]:
                broken_at = row["id"]
                break
            prev_hash = row["entry_hash"]

        return {
            "valid": broken_at is None,
            "entries_checked": len(rows),
            "broken_at_id": broken_at,
        }

    # ── Query Methods ─────────────────────────────────────────────────────────

    async def get_logs(
        self,
        limit: int = 20,
        offset: int = 0,
        benefit_id: Optional[str] = None,
        tier: Optional[str] = None,
    ) -> dict:
        """Paginated audit log retrieval."""
        if not self._pool:
            return {"total": 0, "offset": offset, "limit": limit, "entries": []}

        where_clauses = []
        params: list[Any] = []
        p = 1
        if benefit_id:
            where_clauses.append(f"benefit_id = ${p}")
            params.append(benefit_id)
            p += 1
        if tier:
            where_clauses.append(f"tier = ${p}")
            params.append(tier)
            p += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        async with self._pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM audit_log {where}", *params)
            rows = await conn.fetch(
                f"""
                SELECT id, request_id, session_id, client_ip, query_hash, mode,
                       created_at, complexity_score, tier, llm_model,
                       intent_type, benefit_id, neo4j_nodes, retrieval_audit,
                       eligibility_outcome, eligibility_detail, policy_snapshot,
                       hallucination_guard_triggered, input_tokens, output_tokens,
                       llm_stop_reason, refusal_flag, citation_present, temperature,
                       response_preview, latency_ms, error_detail,
                       entry_hash, previous_hash
                FROM audit_log {where}
                ORDER BY created_at DESC
                LIMIT ${p} OFFSET ${p+1}
                """,
                *params,
                limit,
                offset,
            )

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "entries": [_decrypt_entry(self._crypto, dict(r)) for r in rows],
        }

    async def get_entry(self, request_id: str) -> Optional[dict]:
        """Retrieve a single audit log entry by request_id (for replay)."""
        if not self._pool:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM audit_log WHERE request_id = $1",
                uuid.UUID(request_id),
            )
        return _decrypt_entry(self._crypto, dict(row)) if row else None

    async def get_security_events(
        self,
        limit: int = 50,
        severity: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> dict:
        """Retrieve security events with optional filters."""
        if not self._pool:
            return {"total": 0, "entries": []}

        where_clauses = []
        params: list[Any] = []
        p = 1
        if severity:
            where_clauses.append(f"severity = ${p}")
            params.append(severity)
            p += 1
        if request_id:
            where_clauses.append(f"request_id = ${p}")
            params.append(uuid.UUID(request_id))
            p += 1

        where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        async with self._pool.acquire() as conn:
            total = await conn.fetchval(f"SELECT COUNT(*) FROM security_events {where}", *params)
            rows = await conn.fetch(
                f"""
                SELECT id, request_id, detected_at, event_type, severity,
                       pattern_matched, query_fragment, entry_hash
                FROM security_events {where}
                ORDER BY detected_at DESC
                LIMIT ${p}
                """,
                *params,
                limit,
            )

        return {
            "total": total,
            "entries": [dict(r) for r in rows],
        }

    async def get_routing_stats(self) -> list:
        """Hourly tier routing stats for observability."""
        if not self._pool:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT date_trunc('hour', created_at) AS hour,
                       tier,
                       COUNT(*) AS requests,
                       AVG(complexity_score)::real AS avg_score,
                       AVG(latency_ms)::real AS avg_latency_ms,
                       AVG(input_tokens)::real AS avg_input_tokens,
                       AVG(output_tokens)::real AS avg_output_tokens,
                       COUNT(CASE WHEN eligibility_outcome = TRUE THEN 1 END) AS eligible_count,
                       COUNT(CASE WHEN eligibility_outcome = FALSE THEN 1 END) AS ineligible_count,
                       COUNT(CASE WHEN hallucination_guard_triggered THEN 1 END) AS guard_triggers,
                       COUNT(CASE WHEN refusal_flag THEN 1 END) AS refusals,
                       COUNT(CASE WHEN citation_present THEN 1 END) AS cited_responses
                FROM audit_log
                WHERE created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY 1, 2
                ORDER BY 1 DESC, 2
                """
            )
        return [dict(r) for r in rows]

    async def log_security_event_direct(
        self,
        *,
        event_type: str,
        severity: str,
        pattern_matched: str,
        query_fragment: str,
    ) -> None:
        """
        Log a single security event without a full pipeline context.
        Used for audit endpoint auth failures and other out-of-band events.
        Reuses the existing hash-chained _log_security_events path.
        """
        @dataclass
        class _Event:
            event_type: str
            severity: str
            pattern_matched: str
            query_fragment: str

        await self._log_security_events(
            request_id=str(uuid.uuid4()),
            events=[_Event(event_type, severity, pattern_matched, query_fragment[:200])],
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_hash(entry_data: dict, previous_hash: str) -> str:
    """SHA256(canonical_json(entry_data) + previous_hash)."""
    canonical = json.dumps(entry_data, sort_keys=True, default=str)
    content = canonical + previous_hash
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _json(obj) -> Optional[str]:
    """Serialize to JSON string, or None if obj is None/empty."""
    if obj is None:
        return None
    return json.dumps(obj, default=str)


# ── Schema SQL ────────────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS audit_log (
    id                            BIGSERIAL PRIMARY KEY,
    request_id                    UUID NOT NULL,
    session_id                    VARCHAR(64),
    client_ip                     VARCHAR(45),
    user_query                    TEXT,
    query_hash                    VARCHAR(64),
    mode                          VARCHAR(20) DEFAULT 'connected',
    created_at                    TIMESTAMPTZ DEFAULT NOW(),
    complexity_score              REAL,
    tier                          VARCHAR(10),
    llm_model                     VARCHAR(60),
    intent_type                   VARCHAR(50),
    benefit_id                    VARCHAR(50),
    neo4j_nodes                   JSONB,
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
    governance_meta               JSONB,
    entry_hash                    VARCHAR(64),
    previous_hash                 VARCHAR(64),
    UNIQUE(request_id)
);

CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_benefit_id  ON audit_log (benefit_id);
CREATE INDEX IF NOT EXISTS idx_audit_tier        ON audit_log (tier);
CREATE INDEX IF NOT EXISTS idx_audit_query_hash  ON audit_log (query_hash);
CREATE INDEX IF NOT EXISTS idx_audit_session_id  ON audit_log (session_id);

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

CREATE OR REPLACE VIEW routing_stats AS
SELECT
    date_trunc('hour', created_at)   AS hour,
    tier,
    COUNT(*)                          AS requests,
    ROUND(AVG(complexity_score)::numeric, 2) AS avg_score,
    ROUND(AVG(latency_ms)::numeric, 0)       AS avg_latency_ms,
    ROUND(AVG(input_tokens)::numeric, 0)     AS avg_input_tokens,
    ROUND(AVG(output_tokens)::numeric, 0)    AS avg_output_tokens,
    COUNT(CASE WHEN eligibility_outcome = TRUE  THEN 1 END) AS eligible_count,
    COUNT(CASE WHEN eligibility_outcome = FALSE THEN 1 END) AS ineligible_count,
    COUNT(CASE WHEN hallucination_guard_triggered THEN 1 END) AS guard_triggers,
    COUNT(CASE WHEN refusal_flag   THEN 1 END) AS refusals,
    COUNT(CASE WHEN citation_present THEN 1 END) AS cited_responses
FROM audit_log
WHERE created_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

CREATE OR REPLACE VIEW security_event_summary AS
SELECT
    date_trunc('hour', detected_at) AS hour,
    event_type,
    severity,
    COUNT(*) AS occurrences
FROM security_events
WHERE detected_at >= NOW() - INTERVAL '7 days'
GROUP BY 1, 2, 3
ORDER BY 1 DESC, 4 DESC;

CREATE OR REPLACE VIEW daily_summary AS
SELECT
    date_trunc('day', created_at) AS day,
    COUNT(*)                       AS total_requests,
    COUNT(DISTINCT benefit_id)     AS benefits_queried,
    COUNT(CASE WHEN tier = 'TIER_1' THEN 1 END) AS tier1_count,
    COUNT(CASE WHEN tier = 'TIER_2' THEN 1 END) AS tier2_count,
    COUNT(CASE WHEN tier = 'TIER_3' THEN 1 END) AS tier3_count,
    COUNT(CASE WHEN eligibility_outcome = TRUE  THEN 1 END) AS eligible_count,
    COUNT(CASE WHEN eligibility_outcome = FALSE THEN 1 END) AS ineligible_count,
    ROUND(AVG(latency_ms)::numeric, 0) AS avg_latency_ms,
    SUM(input_tokens)  AS total_input_tokens,
    SUM(output_tokens) AS total_output_tokens,
    COUNT(CASE WHEN hallucination_guard_triggered THEN 1 END) AS guard_triggers,
    COUNT(CASE WHEN refusal_flag     THEN 1 END) AS refusals,
    COUNT(CASE WHEN citation_present THEN 1 END) AS cited_responses
FROM audit_log
GROUP BY 1
ORDER BY 1 DESC;
"""

_INSERT_AUDIT_SQL = """
INSERT INTO audit_log (
    request_id, session_id, client_ip, user_query, query_hash, mode,
    complexity_score, tier, llm_model, intent_type, benefit_id,
    neo4j_nodes, retrieval_audit,
    eligibility_outcome, eligibility_detail, policy_snapshot,
    hallucination_guard_triggered,
    input_tokens, output_tokens, llm_stop_reason,
    refusal_flag, citation_present, temperature,
    response_preview, latency_ms, error_detail,
    governance_meta,
    entry_hash, previous_hash
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
    $12::jsonb, $13::jsonb,
    $14, $15::jsonb, $16::jsonb, $17,
    $18, $19, $20, $21, $22, $23, $24, $25, $26,
    $27::jsonb,
    $28, $29
)
ON CONFLICT (request_id) DO NOTHING
"""

_INSERT_SECURITY_EVENT_SQL = """
INSERT INTO security_events (
    request_id, event_type, severity, pattern_matched, query_fragment,
    entry_hash, previous_hash
) VALUES ($1::uuid, $2, $3, $4, $5, $6, $7)
"""
