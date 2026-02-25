"""
Sovereign Brain — Model Fingerprinting
========================================
Computed once at startup. Captures model config identity for per-request
audit embedding. Stored in governance_meta JSONB column of audit_log.
"""

import hashlib
import json
from dataclasses import asdict, dataclass

# The static (non-dynamic) base system prompt. SHA256 of this string is logged
# per-request as proof that the base instructions have not drifted.
# Must be kept in sync with the static parts of _build_system_prompt() in main.py.
_PROMPT_TEMPLATE_STATIC = (
    "You are the Sovereign AI Benefits Advisor — a government-grade assistant. "
    "CRITICAL RULES: "
    "1. Only cite information from the STRUCTURED POLICY RULES or POLICY DOCUMENTS provided below. "
    "2. Never invent eligibility thresholds, amounts, or conditions. "
    "3. Always cite the specific Rule ID or Document reference when making claims. "
    "4. If asked about eligibility and no authoritative data is available, say so explicitly. "
    "5. Be compassionate, clear, and precise — citizens may be in difficult situations."
)


@dataclass
class ModelFingerprint:
    """
    System-level fingerprint computed at startup.
    Embedded in every audit_log row as governance_meta JSONB.
    """
    config_hash: str           # SHA256(json(tier models + thresholds + temperature))
    embedding_model: str       # e.g., "all-MiniLM-L6-v2"
    prompt_template_hash: str  # SHA256 of static base system prompt
    secure_mode: bool

    @classmethod
    def compute(cls, settings) -> "ModelFingerprint":
        config_dict = {
            "tier1_model": settings.llm_tier1_model,
            "tier2_model": settings.llm_tier2_model,
            "tier3_model": settings.llm_tier3_model,
            "temperature": settings.llm_temperature,
            "tier1_max_score": settings.router_tier1_max_score,
            "tier2_max_score": settings.router_tier2_max_score,
            "secure_mode": settings.secure_mode,
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
        )

    def to_dict(self) -> dict:
        return asdict(self)
