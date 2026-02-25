"""
Behavioral Anomaly Detector
============================
Sliding-window detection for three classes of anomalous query patterns.
Runs entirely in-process (no DB writes for detection logic — only for logging results).
Called via asyncio.create_task() after each chat completion — zero impact on request latency.

Detected anomalies are written to the security_events audit chain as
event_type='behavioral_anomaly_*' with severity='medium'.

Detectors
─────────
1. Session volume spike
   Signal:    >30 queries from the same session_id in a 5-minute window
   Indicates: Automated scraping or rapid eligibility enumeration
   Event:     behavioral_anomaly_volume_spike

2. Unusual document targeting
   Signal:    >5 distinct benefit_ids queried by the same session in a 10-minute window
   Indicates: Broad enumeration of policy coverage (not typical citizen behaviour)
   Event:     behavioral_anomaly_document_targeting

3. Global pattern shift
   Signal:    Current 5-minute query rate exceeds 3× the rolling 1-hour average
              (only evaluated when the 1-hour baseline contains ≥5 queries)
   Indicates: Sudden system-wide load spike, possibly coordinated
   Event:     behavioral_anomaly_pattern_shift

All thresholds are module-level constants and can be tuned without code changes by
wrapping them in config settings if needed.
"""

import asyncio
import logging
import time
from collections import defaultdict, deque
from typing import Optional

from prometheus_client import Counter

log = logging.getLogger("sovereign.anomaly")

ANOMALIES = Counter(
    "sovereign_anomalies_total",
    "Behavioral anomalies detected",
    ["anomaly_type"],
)

# ── Detector thresholds ────────────────────────────────────────────────────────
SESSION_VOLUME_LIMIT   = 30    # max queries per session per SESSION_VOLUME_WINDOW
SESSION_VOLUME_WINDOW  = 300   # seconds (5 minutes)
BENEFIT_BREADTH_LIMIT  = 5     # max distinct benefit_ids per session per BENEFIT_BREADTH_WINDOW
BENEFIT_BREADTH_WINDOW = 600   # seconds (10 minutes)
PATTERN_SHIFT_MULT     = 3.0   # 5m rate must exceed this multiple of 1h avg
PATTERN_SHIFT_BASELINE = 5     # minimum 1h event count before pattern shift comparison activates


class BehavioralAnomalyDetector:
    """
    In-memory, asyncio-safe behavioral anomaly detector.

    All state is protected by a single asyncio.Lock to serialise window updates.
    State grows O(active_sessions) and is never persisted — a restart resets baselines.
    This is intentional: the detector is meant to catch real-time patterns, not
    historical trends (which the audit log already captures).
    """

    def __init__(self, audit_logger):
        self._audit = audit_logger
        # Per-session sliding windows
        self._session_queries: dict[str, deque]              = defaultdict(deque)
        self._session_benefits: dict[str, dict[str, list]]   = defaultdict(lambda: defaultdict(list))
        # Global sliding window (1 hour)
        self._global_queries: deque = deque()
        self._lock = asyncio.Lock()

    async def check(
        self,
        session_id: str,
        benefit_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Analyse the current query against sliding-window baselines.

        Args:
            session_id:  Session identifier from the request (X-Session-ID header).
            benefit_id:  Benefit type being queried (from intent detection), or None.

        Returns:
            List of detected anomaly dicts, each with keys 'type' and 'detail'.
            Empty list when no anomalies are detected.
        """
        now = time.time()
        anomalies: list[dict] = []

        async with self._lock:
            # ── 1. Session volume spike ────────────────────────────────────
            sq = self._session_queries[session_id]
            sq.append(now)
            cutoff_vol = now - SESSION_VOLUME_WINDOW
            while sq and sq[0] < cutoff_vol:
                sq.popleft()
            if len(sq) > SESSION_VOLUME_LIMIT:
                anomalies.append({
                    "type": "behavioral_anomaly_volume_spike",
                    "detail": (
                        f"{len(sq)} queries in {SESSION_VOLUME_WINDOW // 60}m "
                        f"(limit={SESSION_VOLUME_LIMIT}) "
                        f"session={session_id[:16]}..."
                    ),
                })

            # ── 2. Unusual document targeting ──────────────────────────────
            if benefit_id:
                ben = self._session_benefits[session_id]
                ben[benefit_id].append(now)
                cutoff_ben = now - BENEFIT_BREADTH_WINDOW
                # Prune stale timestamps from each tracked benefit
                active = {
                    b: [t for t in ts if t >= cutoff_ben]
                    for b, ts in ben.items()
                }
                # Drop benefits with no recent activity
                active = {b: ts for b, ts in active.items() if ts}
                # Rebuild as defaultdict to maintain the type invariant
                self._session_benefits[session_id] = defaultdict(list, active)
                if len(active) > BENEFIT_BREADTH_LIMIT:
                    anomalies.append({
                        "type": "behavioral_anomaly_document_targeting",
                        "detail": (
                            f"{len(active)} distinct benefit types in "
                            f"{BENEFIT_BREADTH_WINDOW // 60}m "
                            f"(limit={BENEFIT_BREADTH_LIMIT})"
                        ),
                    })

            # ── 3. Global pattern shift ────────────────────────────────────
            self._global_queries.append(now)
            cutoff_hour = now - 3600
            while self._global_queries and self._global_queries[0] < cutoff_hour:
                self._global_queries.popleft()

            hourly_count   = len(self._global_queries)
            five_min_count = sum(1 for t in self._global_queries if t >= now - 300)
            # Avoid division by zero; 12 five-minute buckets per hour
            hourly_avg_5m  = hourly_count / 12
            if (
                hourly_avg_5m >= PATTERN_SHIFT_BASELINE
                and five_min_count > hourly_avg_5m * PATTERN_SHIFT_MULT
            ):
                anomalies.append({
                    "type": "behavioral_anomaly_pattern_shift",
                    "detail": (
                        f"5m rate={five_min_count} vs 1h avg={hourly_avg_5m:.1f} "
                        f"(threshold={PATTERN_SHIFT_MULT}×)"
                    ),
                })

        # ── Log anomalies outside the lock (I/O must not block) ───────────
        for a in anomalies:
            ANOMALIES.labels(anomaly_type=a["type"]).inc()
            log.warning("BEHAVIORAL ANOMALY [%s]: %s", a["type"], a["detail"])
            if self._audit:
                try:
                    await self._audit.log_security_event_direct(
                        event_type=a["type"],
                        severity="medium",
                        pattern_matched=a["type"],
                        query_fragment=a["detail"][:200],
                    )
                except Exception as exc:
                    log.warning("Anomaly security event log failed: %s", exc)

        return anomalies
