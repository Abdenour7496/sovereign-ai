"""
Dual-Control Classified Replay Manager
=======================================
Enforces two-person integrity (TPI) for replaying classified security events.
No single principal can both request and approve a classified replay.

"Classified" means security_events with severity IN ('critical', 'high').

Flow:
  1. Auditor    → POST /api/audit/classified/request          → pending token (1h TTL)
  2. Security Officer → POST /api/audit/classified/approve/{token} → approved (5min TTL)
  3. Auditor    → GET /api/audit/classified/event/{id}?token= → retrieves entry
     (only the same key that requested may retrieve — prevents token theft)

Self-approval is structurally prevented by comparing SHA256(key) at both steps.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from prometheus_client import Counter

log = logging.getLogger("sovereign.dual_control")

DUAL_CONTROL_REQUESTS  = Counter(
    "sovereign_dual_control_requests_total",
    "Dual-control classified replay requests initiated",
)
DUAL_CONTROL_APPROVALS = Counter(
    "sovereign_dual_control_approvals_total",
    "Dual-control classified replay approvals granted",
)

TOKEN_LIFETIME_SECONDS = 3600   # 1 hour: window for security officer to approve
APPROVAL_WINDOW_SECONDS = 300   # 5 min: window for auditor to retrieve after approval

_CLASSIFIED_SEVERITIES = frozenset({"critical", "high"})

_CREATE_TABLE = """
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
"""


class DualControlManager:
    """
    Manages the two-person integrity (TPI) state machine for classified replay tokens.
    Creates and validates replay_tokens table rows in Postgres.
    """

    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Create replay_tokens table if it does not exist (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
        log.info("Dual-control schema ready")

    async def request_replay(
        self,
        security_event_id: int,
        role: str,
        key_hash: str,
        reason: str,
    ) -> dict:
        """
        Step 1: Auditor requests a classified replay token.
        Validates that the target event is classified, then creates a pending token.
        Raises ValueError if event not found or not classified.
        """
        token = secrets.token_hex(32)  # 64 hex chars, cryptographically random
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=TOKEN_LIFETIME_SECONDS)

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, severity FROM security_events WHERE id = $1",
                security_event_id,
            )
            if not row:
                raise ValueError(f"Security event {security_event_id} not found")
            if row["severity"] not in _CLASSIFIED_SEVERITIES:
                raise ValueError(
                    f"Event {security_event_id} has severity='{row['severity']}' — "
                    f"not classified (classified severities: {sorted(_CLASSIFIED_SEVERITIES)}). "
                    f"Use the standard replay endpoint for non-classified events."
                )
            await conn.execute(
                """INSERT INTO replay_tokens
                   (security_event_id, token, requested_by_role,
                    requesting_key_hash, reason, expires_at)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                security_event_id, token, role, key_hash, reason, expires_at,
            )

        DUAL_CONTROL_REQUESTS.inc()
        log.info(
            "Dual-control REQUESTED: event_id=%d role=%s token=%s...",
            security_event_id, role, token[:8],
        )
        return {
            "token": token,
            "security_event_id": security_event_id,
            "status": "pending",
            "expires_at": expires_at.isoformat(),
            "next_step": (
                "A security_officer must POST /api/audit/classified/approve/<token> "
                f"within {TOKEN_LIFETIME_SECONDS // 60} minutes."
            ),
        }

    async def approve_replay(
        self,
        token: str,
        role: str,
        approving_key_hash: str,
    ) -> dict:
        """
        Step 2: Security officer approves a pending token.
        Enforces:
          - Token exists and is 'pending'
          - Token has not expired
          - Approver's key hash differs from requester's key hash (two-person integrity)
        On success, sets status='approved' and resets TTL to APPROVAL_WINDOW_SECONDS.
        Raises ValueError on any violation.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM replay_tokens WHERE token = $1", token
            )
            if not row:
                raise ValueError("Token not found")
            if row["status"] != "pending":
                raise ValueError(
                    f"Token status is '{row['status']}' — only 'pending' tokens can be approved"
                )
            if datetime.now(timezone.utc) > row["expires_at"]:
                raise ValueError(
                    "Token has expired (approval window closed). "
                    "The requester must submit a new request."
                )
            if row["requesting_key_hash"] == approving_key_hash:
                raise ValueError(
                    "Self-approval denied: two-person integrity requires the approver to be "
                    "a different principal from the requester. "
                    "Use a different X-Audit-Key belonging to a security_officer."
                )

            approved_at = datetime.now(timezone.utc)
            retrieval_expires = approved_at + timedelta(seconds=APPROVAL_WINDOW_SECONDS)

            await conn.execute(
                """UPDATE replay_tokens
                   SET status = 'approved',
                       approved_by_role = $1,
                       approved_at = $2,
                       expires_at = $3
                   WHERE token = $4""",
                role, approved_at, retrieval_expires, token,
            )

        DUAL_CONTROL_APPROVALS.inc()
        log.info("Dual-control APPROVED: token=%s... approver_role=%s", token[:8], role)
        return {
            "token": token,
            "status": "approved",
            "valid_for_seconds": APPROVAL_WINDOW_SECONDS,
            "next_step": (
                "Original requester: GET /api/audit/classified/event/<event_id>?token=<token> "
                f"within {APPROVAL_WINDOW_SECONDS} seconds."
            ),
        }

    async def consume_token(
        self,
        token: str,
        security_event_id: int,
        requesting_key_hash: str,
    ) -> bool:
        """
        Step 3 gate: validates and consumes the token.
        Returns True only when ALL conditions are satisfied:
          - Token exists, status='approved'
          - Token is for the requested security_event_id
          - Token has not expired
          - The consuming key_hash matches the requesting_key_hash (same principal)
        On success, marks token as 'used'. Returns False on any failure.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM replay_tokens WHERE token = $1", token
            )
            if not row:
                return False
            if row["status"] != "approved":
                return False
            if row["security_event_id"] != security_event_id:
                return False
            if datetime.now(timezone.utc) > row["expires_at"]:
                return False
            if row["requesting_key_hash"] != requesting_key_hash:
                # Token belongs to a different requester — reject
                return False
            await conn.execute(
                "UPDATE replay_tokens SET status = 'used', used_at = $1 WHERE token = $2",
                datetime.now(timezone.utc), token,
            )
        log.info(
            "Dual-control CONSUMED: token=%s... event_id=%d",
            token[:8], security_event_id,
        )
        return True

    async def get_classified_event(self, security_event_id: int) -> Optional[dict]:
        """Retrieve a security_event record by its integer ID."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM security_events WHERE id = $1", security_event_id
            )
        return dict(row) if row else None
