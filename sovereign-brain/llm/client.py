"""
Sovereign Brain — Multi-Tier LLM Client
=========================================
Routes to Claude API with three model tiers:
  Tier 1 → claude-haiku-4-5-20251001  (simple, fast, cheap)
  Tier 2 → claude-sonnet-4-6           (balanced, high quality)
  Tier 3 → claude-opus-4-6             (maximum reasoning)

The tier is determined by the ComplexityRouter BEFORE calling this client.
This module purely executes the LLM call with the correct model.

Design principles:
  - Low temperature (0.1) for factual, government-grade consistency
  - Streaming support for OpenWebUI real-time display
  - All calls include the structured system prompt built by main.py
  - GenerationMetadata is returned alongside response text for audit logging
"""

import logging
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Optional, Tuple

import anthropic
import httpx

from network.egress_monitor import EgressBlockedError, EgressMonitorTransport

log = logging.getLogger("sovereign.llm")

# System prompt invariant — appended to every call
SAFETY_FOOTER = """

IMPORTANT CONSTRAINTS:
- You are providing information, NOT legal advice
- Always recommend citizens contact the relevant agency to confirm eligibility
- Never guarantee a specific payment amount — rates change
- If you are uncertain, say so explicitly rather than guessing
- Direct complex cases to human advisors
"""

# Patterns that indicate the LLM declined to answer
_REFUSAL_PATTERNS = re.compile(
    r"\b(i\s+cannot|i\s+can't|i'm\s+unable\s+to|i\s+am\s+unable\s+to|"
    r"i\s+must\s+decline|i\s+won't|i\s+will\s+not\s+be\s+able\s+to|"
    r"i\s+don't\s+have\s+(enough|sufficient|the)\s+information)\b",
    re.IGNORECASE,
)

# Patterns indicating the response cites authoritative sources
_CITATION_PATTERNS = re.compile(
    r"\b(section\s+\d|social\s+security\s+act|services\s+australia|"
    r"source:|according\s+to|as\s+per|under\s+(the\s+)?act|"
    r"legislation|legal\s+clause|subsection)",
    re.IGNORECASE,
)


@dataclass
class GenerationMetadata:
    """Audit metadata returned alongside every LLM response."""
    input_tokens: int
    output_tokens: int
    model: str
    stop_reason: str          # "end_turn" | "max_tokens" | "stop_sequence"
    refusal_flag: bool        # LLM declined to answer
    citation_present: bool    # Response cites policy sources
    temperature: float


class StreamWithMetadata:
    """
    Wraps an async generator that yields text chunks.
    After iteration completes, .metadata holds GenerationMetadata.
    Usage in main.py:
        stream = llm.stream(...)
        async for chunk in stream:
            yield chunk
        meta = stream.metadata
    """

    def __init__(self, coro, temperature: float):
        self._coro = coro
        self._temperature = temperature
        self.metadata: Optional[GenerationMetadata] = None

    def __aiter__(self):
        return self._run()

    async def _run(self):
        accumulated = []
        async for chunk in self._coro:
            accumulated.append(chunk)
            yield chunk
        # Store metadata after iteration completes (set by the generator)
        self._accumulated = "".join(accumulated)


class LLMClient:
    """Multi-tier Claude API client for the Sovereign Brain."""

    def __init__(self, settings, on_egress=None):
        self.settings = settings
        transport = EgressMonitorTransport(mode=settings.mode, on_egress=on_egress)
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or "not-configured",
            http_client=httpx.AsyncClient(transport=transport),
        )

    async def generate(
        self,
        messages: list,
        model: str,
        system_prompt: str = "",
        max_tokens: int = None,
    ) -> Tuple[str, GenerationMetadata]:
        """
        Generate a complete response (non-streaming).
        Returns (text, GenerationMetadata) for both content and audit data.
        """
        if self.settings.mode == "airgapped":
            raise EgressBlockedError(
                "LLM unavailable: MODE=airgapped. "
                "Use /api/eligibility/check for deterministic answers."
            )
        max_tok = max_tokens or self.settings.llm_max_tokens
        temperature = 0.0 if self.settings.secure_mode else self.settings.llm_temperature
        system = (system_prompt + SAFETY_FOOTER).strip() if system_prompt else SAFETY_FOOTER

        log.info(f"LLM call: model={model}, messages={len(messages)}, max_tokens={max_tok}")

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tok,
                temperature=temperature,
                system=system,
                messages=messages,
            )
            content = response.content[0].text if response.content else ""
            log.info(
                f"LLM response: {len(content)} chars, "
                f"input_tokens={response.usage.input_tokens}, "
                f"output_tokens={response.usage.output_tokens}"
            )
            meta = GenerationMetadata(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                model=response.model,
                stop_reason=response.stop_reason or "end_turn",
                refusal_flag=bool(_REFUSAL_PATTERNS.search(content)),
                citation_present=bool(_CITATION_PATTERNS.search(content)),
                temperature=temperature,
            )
            return content, meta
        except anthropic.RateLimitError:
            log.warning("Rate limit hit — returning fallback")
            msg = self._rate_limit_message()
            return msg, GenerationMetadata(
                input_tokens=0, output_tokens=0, model=model,
                stop_reason="rate_limit", refusal_flag=True,
                citation_present=False, temperature=temperature,
            )
        except anthropic.APIError as e:
            log.error(f"Anthropic API error: {e}")
            raise

    async def stream(
        self,
        messages: list,
        model: str,
        system_prompt: str = "",
        max_tokens: int = None,
    ) -> AsyncGenerator:
        """
        Stream response chunks (for OpenWebUI real-time display).
        Returns an async generator. After exhausting it, read .metadata
        on the returned object for GenerationMetadata.
        """
        if self.settings.mode == "airgapped":
            raise EgressBlockedError(
                "LLM unavailable: MODE=airgapped. "
                "Use /api/eligibility/check for deterministic answers."
            )
        max_tok = max_tokens or self.settings.llm_max_tokens
        temperature = 0.0 if self.settings.secure_mode else self.settings.llm_temperature
        system = (system_prompt + SAFETY_FOOTER).strip() if system_prompt else SAFETY_FOOTER

        log.info(f"LLM stream: model={model}")
        return self._stream_impl(messages, model, system, max_tok, temperature)

    async def _stream_impl(
        self,
        messages: list,
        model: str,
        system: str,
        max_tok: int,
        temperature: float,
    ):
        """
        Internal async generator that yields text chunks.
        Sets self.metadata after stream completes.
        This is a plain async generator — metadata is attached externally
        via the _StreamContext wrapper used in main.py.
        """
        accumulated = []
        final_message = None

        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tok,
                temperature=temperature,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    accumulated.append(text)
                    yield text
                # Get final message with usage metadata after stream ends
                final_message = await stream.get_final_message()
        except anthropic.RateLimitError:
            msg = self._rate_limit_message()
            accumulated.append(msg)
            yield msg
        except anthropic.APIError as e:
            log.error(f"Anthropic API stream error: {e}")
            error_msg = f"\n\n[Error: {str(e)}]"
            accumulated.append(error_msg)
            yield error_msg

        # Yield metadata as a special sentinel object at end
        # main.py detects this by checking for GenerationMetadata type
        full_text = "".join(accumulated)
        if final_message and final_message.usage:
            meta = GenerationMetadata(
                input_tokens=final_message.usage.input_tokens,
                output_tokens=final_message.usage.output_tokens,
                model=final_message.model,
                stop_reason=final_message.stop_reason or "end_turn",
                refusal_flag=bool(_REFUSAL_PATTERNS.search(full_text)),
                citation_present=bool(_CITATION_PATTERNS.search(full_text)),
                temperature=temperature,
            )
        else:
            meta = GenerationMetadata(
                input_tokens=0, output_tokens=0, model=model,
                stop_reason="unknown", refusal_flag=False,
                citation_present=False, temperature=temperature,
            )
        yield meta  # Sentinel — main.py handles this specially

    async def health_check(self) -> bool:
        """Verify API key and connectivity. Returns False when airgapped (intentional)."""
        if self.settings.mode == "airgapped":
            return False  # LLM intentionally disabled — not an error
        try:
            await self._client.messages.create(
                model=self.settings.llm_tier1_model,
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception:
            return False

    @staticmethod
    def _rate_limit_message() -> str:
        return (
            "I'm currently experiencing high demand. "
            "Please try your question again in a moment, "
            "or contact the relevant government agency directly for immediate assistance."
        )
