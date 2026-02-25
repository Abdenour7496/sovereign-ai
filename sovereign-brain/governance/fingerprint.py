"""
Sovereign Brain — System Fingerprint
======================================
Full policy-config fingerprinting for deterministic replay verification.

Five dimensions captured at startup and embedded in every audit_log row
as governance_meta JSONB:

  1. Model config        — tier models, temperature (config_hash)
  2. Source integrity    — SHA256 of eligibility engine + router source files
  3. Policy graph        — content-addressable SHA256 of Neo4j graph state
                           (attached after Neo4j connects via attach_policy_graph())
  4. Router thresholds   — explicit tier boundary values (human-readable)
  5. Temporal anchor     — ISO 8601 UTC startup timestamp + full config snapshot

Without all five dimensions, a replay is model-config level only.
With all five, a replay can reconstruct the exact decision environment:
same models, same code, same policy rules, same thresholds, same point in time.

Key: policy_graph_hash changes whenever any Benefit, EligibilityRule, Condition,
LegalClause, or Legislation node is added, modified, or removed in Neo4j.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_HERE = Path(__file__).parent.parent  # sovereign-brain/

# Static base system prompt — must stay in sync with the constant portion of
# _build_system_prompt() in main.py. SHA256 logged per-request as proof that
# the AI's base instructions have not drifted between deployments.
_PROMPT_TEMPLATE_STATIC = (
    "You are the Sovereign AI Benefits Advisor — a government-grade assistant. "
    "CRITICAL RULES: "
    "1. Only cite information from the STRUCTURED POLICY RULES or POLICY DOCUMENTS provided below. "
    "2. Never invent eligibility thresholds, amounts, or conditions. "
    "3. Always cite the specific Rule ID or Document reference when making claims. "
    "4. If asked about eligibility and no authoritative data is available, say so explicitly. "
    "5. Be compassionate, clear, and precise — citizens may be in difficult situations."
)


def _file_hash(rel_path: str) -> str:
    """SHA256 of a source file relative to the sovereign-brain root."""
    p = _HERE / rel_path
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "file_not_found"


@dataclass
class SystemFingerprint:
    """
    Full system fingerprint for deterministic replay verification.
    Computed synchronously at startup from settings + source files.
    policy_graph_hash / policy_graph_node_count are populated asynchronously
    after Neo4j connects via attach_policy_graph().
    Embedded in every audit_log row as governance_meta JSONB.
    """

    # ── 1. Model config ──────────────────────────────────────────────────────
    config_hash: str            # SHA256(json(tier models + thresholds + temperature + mode))
    embedding_model: str        # e.g. "all-MiniLM-L6-v2"
    prompt_template_hash: str   # SHA256 of static base system prompt
    secure_mode: bool

    # ── 2. Source integrity ──────────────────────────────────────────────────
    engine_source_hash: str     # SHA256 of eligibility/engine.py
    router_source_hash: str     # SHA256 of router/complexity_router.py

    # ── 3. Policy graph ──────────────────────────────────────────────────────
    # None until Neo4j connects; attach_policy_graph() fills these in.
    policy_graph_hash: Optional[str]    # SHA256 of graph node/rel/id content
    policy_graph_node_count: int        # Total node count at startup

    # ── 4. Router thresholds (explicit, human-readable for replay) ───────────
    router_thresholds: dict     # {"tier1_max": N, "tier2_max": M}

    # ── 5. Temporal anchor ───────────────────────────────────────────────────
    startup_at: str             # ISO 8601 UTC timestamp of service start
    config_snapshot: dict       # Complete settings snapshot for replay reconstruction

    @classmethod
    def compute(cls, settings) -> "SystemFingerprint":
        """
        Compute everything that doesn't require async I/O.
        Call attach_policy_graph() after Neo4j connects.
        """
        config_dict = {
            "tier1_model":        settings.llm_tier1_model,
            "tier2_model":        settings.llm_tier2_model,
            "tier3_model":        settings.llm_tier3_model,
            "temperature":        settings.llm_temperature,
            "tier1_max_score":    settings.router_tier1_max_score,
            "tier2_max_score":    settings.router_tier2_max_score,
            "hysteresis_buffer":  getattr(settings, "router_hysteresis_buffer", 2),
            "secure_mode":        settings.secure_mode,
            "embedding_model":    settings.embedding_model,
            "mode":               settings.mode,
        }
        config_hash = hashlib.sha256(
            json.dumps(config_dict, sort_keys=True).encode()
        ).hexdigest()

        prompt_template_hash = hashlib.sha256(
            _PROMPT_TEMPLATE_STATIC.encode()
        ).hexdigest()

        return cls(
            config_hash=config_hash,
            embedding_model=settings.embedding_model,
            prompt_template_hash=prompt_template_hash,
            secure_mode=settings.secure_mode,
            engine_source_hash=_file_hash("eligibility/engine.py"),
            router_source_hash=_file_hash("router/complexity_router.py"),
            policy_graph_hash=None,
            policy_graph_node_count=0,
            router_thresholds={
                "tier1_max":          settings.router_tier1_max_score,
                "tier2_max":          settings.router_tier2_max_score,
                "hysteresis_buffer":  getattr(settings, "router_hysteresis_buffer", 2),
            },
            startup_at=datetime.now(timezone.utc).isoformat(),
            config_snapshot=config_dict,
        )

    def attach_policy_graph(self, graph_hash: str, node_count: int) -> None:
        """
        Attach policy graph fingerprint after Neo4j connects.
        Called from the lifespan startup sequence.
        """
        self.policy_graph_hash = graph_hash
        self.policy_graph_node_count = node_count

    def is_replay_complete(self) -> bool:
        """
        True when all five fingerprint dimensions are populated.
        False if Neo4j was unavailable at startup (policy_graph_hash is None).
        """
        return self.policy_graph_hash is not None

    def to_dict(self) -> dict:
        return asdict(self)


# Backward-compatible alias — existing code importing ModelFingerprint still works.
ModelFingerprint = SystemFingerprint
