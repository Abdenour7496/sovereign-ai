"""
Hash Chain Anchoring
=====================
Periodically captures the current tail-hash of both audit chains and:

  1. Writes a row to chain_anchors Postgres table  (always)
  2. Appends a JSON line to /app/chain-anchors.jsonl  (always — survives DB wipe)
  3. Submits to a public RFC 3161 TSA for external timestamping  (connected mode only)

An anchor proves the chain existed in a known state at a specific moment in time.
Any future tampering that retroactively rewrites hashes earlier than the anchor
is detectable: the anchor_hash will no longer match a recomputed value.

Anchor hash formula:
  anchor_hash = SHA256(f"{main_chain_hash}:{security_chain_hash}:{iso_timestamp}")

This binds both chain tails to an exact timestamp. The TSA response (if obtained)
provides a cryptographic external witness that cannot be forged retroactively.

RFC 3161 implementation is fully self-contained — no external packages required.
Uses only Python stdlib (hashlib, struct, os) + httpx (already a project dependency).
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import asyncpg
import httpx
from prometheus_client import Counter, Gauge

log = logging.getLogger("sovereign.chain_anchor")

ANCHOR_TOTAL = Counter(
    "sovereign_chain_anchors_total",
    "Hash chain anchors completed",
    ["anchor_type"],  # offline | external_tsa
)
ANCHOR_TIMESTAMP = Gauge(
    "sovereign_chain_anchor_last_timestamp_seconds",
    "Unix timestamp of the last successful offline hash chain anchor",
)

DEFAULT_INTERVAL_SECONDS = 3600       # 1 hour
OFFLINE_JSONL_PATH       = Path("/app/chain-anchors.jsonl")

# RFC 3161 Timestamp Authorities (free, publicly trusted)
_TSA_URLS = [
    "http://timestamp.sectigo.com",   # Sectigo (Comodo) — major CA
    "http://freetsa.org/tsr",          # FreeTSA — reliable free option
]

_CREATE_TABLE = """
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
"""


class ChainAnchor:
    """
    Periodic hash chain anchoring service.
    Run anchor_now() on demand or start run_periodic() as a background task.
    """

    def __init__(
        self,
        pool: asyncpg.Pool,
        mode: str,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ):
        self._pool = pool
        self._mode = mode
        self._interval = interval_seconds

    async def ensure_schema(self) -> None:
        """Create chain_anchors table if it does not exist (idempotent)."""
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
        log.info("Chain anchor schema ready")

    async def run_periodic(self) -> None:
        """
        Background task: anchor the chain every interval_seconds.
        Errors are logged but do not terminate the loop.
        """
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.anchor_now()
            except Exception as exc:
                log.error("Periodic chain anchor failed: %s", exc)

    async def anchor_now(self) -> dict:
        """
        Capture the current chain state, write offline anchor, and
        optionally submit to RFC 3161 TSA (connected mode only).
        Returns the anchor record dict.
        """
        # ── 1. Read current chain tail hashes ─────────────────────────────
        async with self._pool.acquire() as conn:
            main_row = await conn.fetchrow(
                "SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1"
            )
            main_count_row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM audit_log")
            sec_row = await conn.fetchrow(
                "SELECT entry_hash FROM security_events ORDER BY id DESC LIMIT 1"
            )
            sec_count_row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM security_events")

        main_hash = main_row["entry_hash"] if main_row else "EMPTY"
        main_len  = int(main_count_row["cnt"]) if main_count_row else 0
        sec_hash  = sec_row["entry_hash"] if sec_row else "EMPTY"
        sec_len   = int(sec_count_row["cnt"]) if sec_count_row else 0

        ts_iso = datetime.now(timezone.utc).isoformat()

        # ── 2. Compute anchor hash ─────────────────────────────────────────
        anchor_hash = hashlib.sha256(
            f"{main_hash}:{sec_hash}:{ts_iso}".encode()
        ).hexdigest()

        record = {
            "anchored_at":           ts_iso,
            "main_chain_hash":       main_hash,
            "main_chain_length":     main_len,
            "security_chain_hash":   sec_hash,
            "security_chain_length": sec_len,
            "anchor_hash":           anchor_hash,
            "anchor_type":           "offline",
        }

        # ── 3. Offline storage ─────────────────────────────────────────────
        await self._store_in_db(record, tsa_url=None, external_ref=None)
        await self._write_jsonl(record)
        ANCHOR_TOTAL.labels(anchor_type="offline").inc()
        ANCHOR_TIMESTAMP.set(time.time())
        log.info(
            "Chain anchored [offline]: main=%s... sec=%s... anchor=%s...",
            main_hash[:8], sec_hash[:8], anchor_hash[:8],
        )

        # ── 4. RFC 3161 external TSA (connected mode, best-effort) ─────────
        if self._mode == "connected":
            tsa_result = await self._submit_tsa(anchor_hash)
            if tsa_result:
                tsa_record = {
                    **record,
                    "anchor_type":        "external_tsa",
                    "external_reference": tsa_result["token_b64"],
                    "tsa_url":            tsa_result["url"],
                }
                await self._store_in_db(
                    tsa_record,
                    tsa_url=tsa_result["url"],
                    external_ref=tsa_result["token_b64"],
                )
                ANCHOR_TOTAL.labels(anchor_type="external_tsa").inc()
                record["anchor_type"] = "external_tsa"
                record["tsa_url"]     = tsa_result["url"]
                log.info("Chain anchored [TSA]: %s", tsa_result["url"])

        return record

    async def get_recent_anchors(self, limit: int = 20) -> list:
        """Return recent anchor records for the API response."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, anchored_at, main_chain_hash, main_chain_length,
                          security_chain_hash, security_chain_length,
                          anchor_hash, anchor_type, tsa_url
                   FROM chain_anchors
                   ORDER BY anchored_at DESC
                   LIMIT $1""",
                limit,
            )
        result = []
        for r in rows:
            d = dict(r)
            if d.get("anchored_at"):
                d["anchored_at"] = d["anchored_at"].isoformat()
            result.append(d)
        return result

    # ── Private helpers ────────────────────────────────────────────────────

    async def _store_in_db(self, rec: dict, tsa_url: Optional[str], external_ref: Optional[str]):
        async with self._pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO chain_anchors
                   (anchored_at, main_chain_hash, main_chain_length,
                    security_chain_hash, security_chain_length,
                    anchor_hash, anchor_type, external_reference, tsa_url)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)""",
                datetime.fromisoformat(rec["anchored_at"]),
                rec["main_chain_hash"],
                int(rec["main_chain_length"]),
                rec["security_chain_hash"],
                int(rec["security_chain_length"]),
                rec["anchor_hash"],
                rec["anchor_type"],
                external_ref,
                tsa_url,
            )

    async def _write_jsonl(self, rec: dict) -> None:
        """Append anchor record to local JSONL file (backup that survives DB wipe)."""
        try:
            OFFLINE_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
            with OFFLINE_JSONL_PATH.open("a") as fh:
                fh.write(json.dumps(rec) + "\n")
        except Exception as exc:
            log.warning("Chain anchor JSONL write failed: %s", exc)

    async def _submit_tsa(self, anchor_hash_hex: str) -> Optional[dict]:
        """
        Submit anchor_hash to an RFC 3161 Timestamp Authority.
        Returns {token_b64, url} on success, None if all TSAs fail.
        Errors are non-fatal — offline anchoring already succeeded.
        """
        hash_bytes = bytes.fromhex(anchor_hash_hex)
        tsr_bytes  = _build_tsr(hash_bytes)

        for url in _TSA_URLS:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.post(
                        url,
                        content=tsr_bytes,
                        headers={"Content-Type": "application/timestamp-query"},
                    )
                if response.status_code == 200 and response.content:
                    return {
                        "token_b64": base64.b64encode(response.content).decode(),
                        "url": url,
                    }
                log.debug("TSA %s returned HTTP %d", url, response.status_code)
            except Exception as exc:
                log.debug("TSA %s unreachable: %s", url, exc)

        log.info("All TSAs unavailable — offline anchor only")
        return None


# ── RFC 3161 TimeStampRequest builder (no external packages) ─────────────────
#
# Builds a minimal DER-encoded TimeStampRequest per RFC 3161 § 2.4.2.
# Only SHA-256 is supported (OID 2.16.840.1.101.3.4.2.1).
# The nonce is 8 random bytes; certReq is set to TRUE.
#
# ASN.1 structure:
#   TimeStampReq ::= SEQUENCE {
#     version        INTEGER { v1(1) },
#     messageImprint MessageImprint,
#     nonce          INTEGER OPTIONAL,
#     certReq        BOOLEAN DEFAULT FALSE
#   }
#   MessageImprint ::= SEQUENCE {
#     hashAlgorithm  AlgorithmIdentifier,
#     hashedMessage  OCTET STRING
#   }

def _build_tsr(hash_bytes: bytes) -> bytes:
    """Build RFC 3161 TimeStampRequest (DER) for a 32-byte SHA-256 hash."""
    # SHA-256 OID: 2.16.840.1.101.3.4.2.1
    sha256_oid = bytes([
        0x06, 0x09,
        0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01,
    ])
    # AlgorithmIdentifier: SEQUENCE { OID, NULL }
    alg_id = _seq(sha256_oid + bytes([0x05, 0x00]))
    # hashedMessage: OCTET STRING (32 bytes for SHA-256)
    hashed_msg = bytes([0x04, 0x20]) + hash_bytes
    # MessageImprint: SEQUENCE { AlgorithmIdentifier, OCTET STRING }
    msg_imprint = _seq(alg_id + hashed_msg)
    # version: INTEGER 1
    version = bytes([0x02, 0x01, 0x01])
    # nonce: INTEGER (8 random bytes, DER-positive)
    nonce_b = os.urandom(8)
    if nonce_b[0] & 0x80:          # ensure positive (high bit clear)
        nonce_b = b"\x00" + nonce_b
    nonce = bytes([0x02, len(nonce_b)]) + nonce_b
    # certReq: BOOLEAN TRUE
    cert_req = bytes([0x01, 0x01, 0xff])
    # TimeStampReq: SEQUENCE { version, messageImprint, nonce, certReq }
    return _seq(version + msg_imprint + nonce + cert_req)


def _seq(content: bytes) -> bytes:
    """Wrap content in a DER SEQUENCE tag."""
    return bytes([0x30]) + _der_len(len(content)) + content


def _der_len(n: int) -> bytes:
    """Encode a DER length value."""
    if n < 0x80:
        return bytes([n])
    if n < 0x100:
        return bytes([0x81, n])
    if n < 0x10000:
        return bytes([0x82, n >> 8, n & 0xFF])
    raise ValueError(f"DER length {n} exceeds supported range")
