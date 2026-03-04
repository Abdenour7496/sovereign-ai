"""
Sovereign Brain — LLM Provider Abstraction
===========================================
Defines the common interface and shared types for all LLM providers.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, Tuple


# ── Shared patterns ────────────────────────────────────────────────────────────

SAFETY_FOOTER = """

IMPORTANT CONSTRAINTS:
- You are providing information, NOT legal advice
- Always recommend citizens contact the relevant agency to confirm eligibility
- Never guarantee a specific payment amount — rates change
- If you are uncertain, say so explicitly rather than guessing
- Direct complex cases to human advisors
"""

_REFUSAL_PATTERNS = re.compile(
    r"\b(i\s+cannot|i\s+can't|i'm\s+unable\s+to|i\s+am\s+unable\s+to|"
    r"i\s+must\s+decline|i\s+won't|i\s+will\s+not\s+be\s+able\s+to|"
    r"i\s+don't\s+have\s+(enough|sufficient|the)\s+information)\b",
    re.IGNORECASE,
)

_CITATION_PATTERNS = re.compile(
    r"\b(section\s+\d|social\s+security\s+act|services\s+australia|"
    r"source:|according\s+to|as\s+per|under\s+(the\s+)?act|"
    r"legislation|legal\s+clause|subsection)",
    re.IGNORECASE,
)


# ── Shared data types ──────────────────────────────────────────────────────────

@dataclass
class GenerationMetadata:
    """Audit metadata returned alongside every LLM response."""
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str          # "end_turn" | "max_tokens" | "stop_sequence" | "stop"
    refusal_flag: bool        # LLM declined to answer
    citation_present: bool    # Response cites policy sources
    temperature: float


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """Abstract interface that all LLM providers must implement."""

    @abstractmethod
    async def generate(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, GenerationMetadata]:
        """
        Non-streaming generation.
        Returns (response_text, GenerationMetadata).
        """
        ...

    @abstractmethod
    async def stream_impl(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator:
        """
        Streaming generation.
        Async generator that yields text chunks, then a GenerationMetadata
        sentinel as the final yielded value. Callers detect the sentinel
        by checking isinstance(chunk, GenerationMetadata).
        """
        ...

    @abstractmethod
    async def health_check(self, model: str) -> bool:
        """Verify the provider is reachable and the model is accessible."""
        ...

    @staticmethod
    def _rate_limit_message() -> str:
        return (
            "I'm currently experiencing high demand. "
            "Please try your question again in a moment, "
            "or contact the relevant government agency directly for immediate assistance."
        )
