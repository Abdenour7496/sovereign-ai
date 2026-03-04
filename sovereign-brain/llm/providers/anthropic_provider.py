"""
Sovereign Brain — Anthropic Claude Provider
============================================
Wraps the Anthropic SDK for Claude Haiku / Sonnet / Opus.
"""

import logging
from typing import AsyncGenerator, Tuple

import anthropic
import httpx

from llm.providers.base import (
    BaseProvider,
    GenerationMetadata,
    SAFETY_FOOTER,
    _REFUSAL_PATTERNS,
    _CITATION_PATTERNS,
)

log = logging.getLogger("sovereign.llm.anthropic")


class AnthropicProvider(BaseProvider):
    """Anthropic Claude API (native SDK)."""

    def __init__(self, api_key: str, egress_transport=None):
        http_client = (
            httpx.AsyncClient(transport=egress_transport) if egress_transport else None
        )
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or "not-configured",
            http_client=http_client,
        )

    async def generate(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> Tuple[str, GenerationMetadata]:
        system = (system_prompt + SAFETY_FOOTER).strip() if system_prompt else SAFETY_FOOTER.strip()
        log.info(f"Anthropic generate: model={model}, messages={len(messages)}")

        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            )
            content = response.content[0].text if response.content else ""
            log.info(
                f"Anthropic response: {len(content)} chars, "
                f"in={response.usage.input_tokens}, out={response.usage.output_tokens}"
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
            log.warning("Anthropic rate limit hit — returning fallback")
            msg = self._rate_limit_message()
            return msg, GenerationMetadata(
                input_tokens=0, output_tokens=0, model=model,
                stop_reason="rate_limit", refusal_flag=True,
                citation_present=False, temperature=temperature,
            )
        except anthropic.APIError as e:
            log.error(f"Anthropic API error: {e}")
            raise

    async def stream_impl(
        self,
        messages: list,
        model: str,
        system_prompt: str,
        max_tokens: int,
        temperature: float,
    ) -> AsyncGenerator:
        system = (system_prompt + SAFETY_FOOTER).strip() if system_prompt else SAFETY_FOOTER.strip()
        log.info(f"Anthropic stream: model={model}")
        accumulated = []
        final_message = None

        try:
            async with self._client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    accumulated.append(text)
                    yield text
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
        yield meta  # Sentinel — detected by isinstance(chunk, GenerationMetadata)

    async def health_check(self, model: str) -> bool:
        try:
            await self._client.messages.create(
                model=model,
                max_tokens=5,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except Exception:
            return False
