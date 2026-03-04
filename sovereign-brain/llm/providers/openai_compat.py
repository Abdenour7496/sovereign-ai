"""
Sovereign Brain — OpenAI-Compatible Provider
=============================================
Single implementation that covers every provider exposing an OpenAI-compatible
chat completions API:

  Provider      | Base URL (default)                                         | Key env var
  --------------|------------------------------------------------------------|-----------------------
  openai        | https://api.openai.com/v1                                  | OPENAI_API_KEY
  groq          | https://api.groq.com/openai/v1                             | GROQ_API_KEY
  openrouter    | https://openrouter.ai/api/v1                               | OPENROUTER_API_KEY
  gemini        | https://generativelanguage.googleapis.com/v1beta/openai/   | GEMINI_API_KEY
  ollama        | http://localhost:11434/v1 (or OLLAMA_BASE_URL)             | "ollama" (no real key)
  custom        | CUSTOM_LLM_BASE_URL                                        | CUSTOM_LLM_API_KEY

All providers share the same streaming/non-streaming logic. Token counts
are populated when the provider includes usage data; otherwise they default
to 0 (acceptable for audit logging — provider may not expose token usage).
"""

import logging
from typing import AsyncGenerator, Tuple

import httpx
from openai import AsyncOpenAI

from llm.providers.base import (
    BaseProvider,
    GenerationMetadata,
    SAFETY_FOOTER,
    _REFUSAL_PATTERNS,
    _CITATION_PATTERNS,
)

log = logging.getLogger("sovereign.llm.openai_compat")


class OpenAICompatibleProvider(BaseProvider):
    """
    OpenAI chat completions API client.
    Works with OpenAI, Groq, OpenRouter, Ollama, Gemini, and any
    other provider that mirrors the OpenAI API surface.
    """

    def __init__(self, api_key: str, base_url: str, egress_transport=None):
        http_client = (
            httpx.AsyncClient(transport=egress_transport) if egress_transport else None
        )
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
            http_client=http_client,
        )
        self._base_url = base_url

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_messages(self, messages: list, system_prompt: str) -> list:
        """
        Prepend the system message for OpenAI-style APIs.
        (Anthropic uses a separate `system` param; OpenAI inlines it as a message.)
        """
        system = (
            (system_prompt + SAFETY_FOOTER).strip()
            if system_prompt
            else SAFETY_FOOTER.strip()
        )
        return [{"role": "system", "content": system}, *messages]

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        msg = str(exc).lower()
        return "rate" in msg and "limit" in msg

    # ── BaseProvider interface ─────────────────────────────────────────────────

    async def generate(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, GenerationMetadata]:
        full_messages = self._build_messages(messages, system_prompt)
        log.info(f"OpenAI-compat generate: model={model} via {self._base_url}")

        try:
            response = await self._client.chat.completions.create(
                model=model,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            choice = response.choices[0] if response.choices else None
            content = choice.message.content or "" if choice else ""
            usage = response.usage

            log.info(
                f"OpenAI-compat response: {len(content)} chars, "
                f"in={usage.prompt_tokens if usage else '?'}, "
                f"out={usage.completion_tokens if usage else '?'}"
            )

            meta = GenerationMetadata(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                model=response.model or model,
                stop_reason=choice.finish_reason or "stop" if choice else "unknown",
                refusal_flag=bool(_REFUSAL_PATTERNS.search(content)),
                citation_present=bool(_CITATION_PATTERNS.search(content)),
                temperature=temperature,
            )
            return content, meta

        except Exception as e:
            if self._is_rate_limit(e):
                log.warning(f"Rate limit hit ({self._base_url}) — returning fallback")
                msg = self._rate_limit_message()
                return msg, GenerationMetadata(
                    input_tokens=0, output_tokens=0, model=model,
                    stop_reason="rate_limit", refusal_flag=True,
                    citation_present=False, temperature=temperature,
                )
            log.error(f"OpenAI-compat API error ({self._base_url}): {e}")
            raise

    async def stream_impl(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator:
        full_messages = self._build_messages(messages, system_prompt)
        log.info(f"OpenAI-compat stream: model={model} via {self._base_url}")

        accumulated: list[str] = []
        input_tokens = 0
        output_tokens = 0
        finish_reason = "stop"

        try:
            # stream_options/include_usage is supported by OpenAI, Groq, OpenRouter.
            # For providers that don't support it (e.g. some Ollama versions),
            # it's silently ignored and token counts remain 0.
            stream = await self._client.chat.completions.create(
                model=model,
                messages=full_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
            )

            async for chunk in stream:
                if chunk.choices:
                    delta_content = chunk.choices[0].delta.content
                    if delta_content:
                        accumulated.append(delta_content)
                        yield delta_content
                    if chunk.choices[0].finish_reason:
                        finish_reason = chunk.choices[0].finish_reason

                # Usage arrives in the final chunk (when include_usage=True)
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0

        except Exception as e:
            if self._is_rate_limit(e):
                msg = self._rate_limit_message()
                accumulated.append(msg)
                yield msg
            else:
                log.error(f"OpenAI-compat stream error ({self._base_url}): {e}")
                error_msg = f"\n\n[Error: {str(e)}]"
                accumulated.append(error_msg)
                yield error_msg

        full_text = "".join(accumulated)
        yield GenerationMetadata(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=model,
            stop_reason=finish_reason,
            refusal_flag=bool(_REFUSAL_PATTERNS.search(full_text)),
            citation_present=bool(_CITATION_PATTERNS.search(full_text)),
            temperature=temperature,
        )

    async def health_check(self, model: str) -> bool:
        try:
            await self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=5,
            )
            return True
        except Exception:
            return False
