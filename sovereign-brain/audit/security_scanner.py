"""
Sovereign Brain — Security Event Scanner
=========================================
Detects prompt injection attempts, system probes, jailbreak patterns, and
other adversarial inputs before they reach the LLM.

Returns a list of SecurityEvent objects (empty if the query is clean).
Events are logged to the security_events Postgres table with their own
hash chain, independently of the main audit_log chain.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import Optional


# ── Pattern Registry ──────────────────────────────────────────────────────────
# Each entry: (regex, event_type, severity)
# Severity: "low" | "medium" | "high" | "critical"

_RAW_PATTERNS: list[tuple[str, str, str]] = [
    # Instruction override
    (r"ignore\s+(previous|all|prior)\s+instructions?", "prompt_injection", "high"),
    (r"disregard\s+(previous|all|prior|your|the)\s+", "prompt_injection", "high"),
    (r"forget\s+(your|all|the|previous)\s+instructions?", "prompt_injection", "medium"),
    (r"do\s+not\s+follow\s+(your|the|previous|prior)\s+", "prompt_injection", "medium"),
    (r"override\s+(your|the|all|any)\s+(instructions?|rules?|guidelines?|prompt)", "override_attempt", "high"),
    (r"bypass\s+(your|the|all|any|safety|ethical)\s+", "override_attempt", "medium"),

    # System prompt extraction
    (r"(system\s*prompt|<\s*/?system\s*>)", "system_probe", "high"),
    (r"reveal\s+(your|the)\s+(instructions?|prompt|system|context)", "system_probe", "medium"),
    (r"show\s+me\s+(your|the)\s+(prompt|instructions?|system|context)", "system_probe", "medium"),
    (r"what\s+(are|were)\s+your\s+(instructions?|guidelines?|rules?)", "system_probe", "low"),
    (r"(print|output|display|repeat|echo)\s+(your|the)\s+(system\s*prompt|instructions?)", "system_probe", "high"),
    (r"(tell|show)\s+me\s+what\s+you\s+(were|are)\s+told", "system_probe", "low"),

    # Role override / persona injection
    (r"\bact\s+as\s+(a|an|the)\s+", "role_override", "medium"),
    (r"pretend\s+(to\s+be|you\s+are|that\s+you\s+are)\s+", "role_override", "medium"),
    (r"you\s+are\s+now\s+(a|an|the|in\s+)\s*", "role_override", "medium"),
    (r"from\s+now\s+on\s+(you\s+are|act\s+as|behave\s+as)", "role_override", "medium"),
    (r"roleplay\s+as\s+", "role_override", "low"),

    # Known jailbreak keywords
    (r"\bDAN\b", "jailbreak_attempt", "high"),
    (r"jailbreak", "jailbreak_attempt", "high"),
    (r"developer\s+mode", "jailbreak_attempt", "high"),
    (r"god\s*mode\s*(enabled|on|activate)", "jailbreak_attempt", "high"),
    (r"\[JAILBREAK\]", "jailbreak_attempt", "critical"),
    (r"do\s+anything\s+now", "jailbreak_attempt", "high"),

    # Data extraction patterns
    (r"(extract|dump|export|output)\s+(all|the|every|raw)\s+(data|information|records|logs?)", "data_extraction", "medium"),
    (r"list\s+all\s+(users?|documents?|records?|files?|data)", "data_extraction", "low"),

    # Unusual instruction injection via encoding / delimiter abuse
    (r"```\s*system\s*", "injection_via_code_block", "high"),
    (r"<\s*/?(?:human|assistant|user|ai)\s*>", "role_delimiter_injection", "high"),
    (r"\[\s*INST\s*\]|\[\/\s*INST\s*\]", "role_delimiter_injection", "high"),  # Llama-style
    (r"Human:\s*Assistant:", "role_delimiter_injection", "medium"),
]

# Compile patterns once at module load
_COMPILED: list[tuple[re.Pattern, str, str]] = [
    (re.compile(pat, re.IGNORECASE | re.DOTALL), evt, sev)
    for pat, evt, sev in _RAW_PATTERNS
]

_SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class SecurityEvent:
    event_type: str
    severity: str
    pattern_matched: str
    query_fragment: str        # ≤200 chars surrounding the match (not full query)


@dataclass
class ScanResult:
    clean: bool
    events: list[SecurityEvent] = field(default_factory=list)

    @property
    def max_severity(self) -> Optional[str]:
        if not self.events:
            return None
        return max(self.events, key=lambda e: _SEVERITY_RANK[e.severity]).severity

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "max_severity": self.max_severity,
            "events": [
                {
                    "event_type": e.event_type,
                    "severity": e.severity,
                    "pattern_matched": e.pattern_matched,
                    "query_fragment": e.query_fragment,
                }
                for e in self.events
            ],
        }


# ── Scanner ───────────────────────────────────────────────────────────────────

def scan(query: str) -> ScanResult:
    """
    Scan a user query for adversarial patterns.

    Returns a ScanResult with .clean=True if no patterns matched, or
    .clean=False with a list of SecurityEvent objects describing what was found.
    Processing continues regardless — events are logged, not used to block.
    (Blocking policy is left to the caller / policy layer.)
    """
    if not query:
        return ScanResult(clean=True)

    events: list[SecurityEvent] = []

    for pattern, event_type, severity in _COMPILED:
        match = pattern.search(query)
        if match:
            # Extract a small context window around the match (≤200 chars)
            start = max(0, match.start() - 40)
            end = min(len(query), match.end() + 40)
            fragment = query[start:end].strip()
            if len(fragment) > 200:
                fragment = fragment[:197] + "..."

            events.append(SecurityEvent(
                event_type=event_type,
                severity=severity,
                pattern_matched=pattern.pattern,
                query_fragment=fragment,
            ))

    return ScanResult(clean=len(events) == 0, events=events)


def query_hash(query: str) -> str:
    """SHA256 hash of a query string, for indexing without storing plaintext."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest()
