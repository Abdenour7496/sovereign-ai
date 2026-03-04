"""
Sovereign Brain — Multi-Provider LLM Client
============================================
Provider-agnostic dispatcher that routes calls to the correct backend based
on per-tier configuration.

Supported providers (set via LLM_TIER{1,2,3}_PROVIDER):
  anthropic   — Claude Haiku / Sonnet / Opus (native Anthropic SDK)
  openai      — GPT-4o, GPT-4o-mini, etc. (OpenAI API)
  gemini      — Gemini 1.5 Flash / Pro (Google OpenAI-compat endpoint)
  groq        — Llama-3, Mixtral, etc. (Groq Cloud)
  openrouter  — Any model via OpenRouter aggregator
  ollama      — Any local model via Ollama (self-hosted)
  custom      — Any OpenAI-compatible endpoint (CUSTOM_LLM_BASE_URL)

The tier is determined by ComplexityRouter BEFORE calling this client.
This module only executes the LLM call with the routed model.

Public interface is unchanged — main.py imports GenerationMetadata and
LLMClient from here exactly as before.
"""

import logging
from typing import AsyncGenerator, Optional, Tuple

from network.egress_monitor import EgressBlockedError, EgressMonitorTransport

# Re-export GenerationMetadata so main.py import stays unchanged
from llm.providers.base import BaseProvider, GenerationMetadata  # noqa: F401
from llm.providers.anthropic_provider import AnthropicProvider
from llm.providers.openai_compat import OpenAICompatibleProvider

log = logging.getLogger("sovereign.llm")

# ── Provider factory ───────────────────────────────────────────────────────────

# Default base URLs for each named OpenAI-compatible provider
_OPENAI_COMPAT_DEFAULTS: dict[str, str] = {
    "openai":      "https://api.openai.com/v1",
    "groq":        "https://api.groq.com/openai/v1",
    "openrouter":  "https://openrouter.ai/api/v1",
    "gemini":      "https://generativelanguage.googleapis.com/v1beta/openai/",
    # ollama and custom are resolved from settings (no hardcoded default)
}


def _make_provider(provider_name: str, settings, transport) -> BaseProvider:
    """
    Instantiate the correct provider for a given tier.
    `provider_name` matches the LLM_TIER{n}_PROVIDER env var value.
    """
    name = provider_name.strip().lower()

    if name == "anthropic":
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            egress_transport=transport,
        )

    # All OpenAI-compatible providers share the same implementation
    key_map = {
        "openai":     settings.openai_api_key,
        "groq":       settings.groq_api_key,
        "openrouter": settings.openrouter_api_key,
        "gemini":     settings.gemini_api_key,
        "ollama":     "ollama",          # Ollama doesn't need a real API key
        "custom":     settings.custom_llm_api_key,
    }
    url_map = {
        "openai":     settings.openai_base_url,
        "groq":       settings.groq_base_url,
        "openrouter": settings.openrouter_base_url,
        "gemini":     settings.gemini_base_url,
        "ollama":     settings.ollama_base_url,
        "custom":     settings.custom_llm_base_url,
    }

    if name in key_map:
        api_key = key_map[name]
        base_url = url_map[name]
        if not base_url:
            raise ValueError(
                f"Provider '{name}' requires a base URL. "
                f"Set the corresponding *_BASE_URL environment variable."
            )
        return OpenAICompatibleProvider(
            api_key=api_key,
            base_url=base_url,
            egress_transport=transport,
        )

    raise ValueError(
        f"Unknown LLM provider: '{provider_name}'. "
        f"Valid options: anthropic, openai, gemini, groq, openrouter, ollama, custom"
    )


# ── LLMClient ─────────────────────────────────────────────────────────────────

class LLMClient:
    """
    Multi-tier, multi-provider LLM client for the Sovereign Brain.

    Builds one provider instance per tier at startup, then dispatches
    generate() / stream() calls to the correct provider based on the
    model name returned by ComplexityRouter.
    """

    def __init__(self, settings, on_egress=None):
        self.settings = settings
        transport = EgressMonitorTransport(mode=settings.mode, on_egress=on_egress)

        # One provider instance per tier (may share the same backend)
        self._tier_providers: dict[str, BaseProvider] = {
            "TIER_1": _make_provider(settings.llm_tier1_provider, settings, transport),
            "TIER_2": _make_provider(settings.llm_tier2_provider, settings, transport),
            "TIER_3": _make_provider(settings.llm_tier3_provider, settings, transport),
        }

        # Model name → tier lookup (built in reverse priority so that when
        # the same model string appears in multiple tiers, the lowest tier wins,
        # keeping behaviour consistent with the original single-provider setup).
        self._model_to_tier: dict[str, str] = {}
        for tier, attr in [
            ("TIER_3", "llm_tier3_model"),
            ("TIER_2", "llm_tier2_model"),
            ("TIER_1", "llm_tier1_model"),
        ]:
            self._model_to_tier[getattr(settings, attr)] = tier

        log.info(
            "LLM providers initialised: "
            f"T1={settings.llm_tier1_provider}/{settings.llm_tier1_model}, "
            f"T2={settings.llm_tier2_provider}/{settings.llm_tier2_model}, "
            f"T3={settings.llm_tier3_provider}/{settings.llm_tier3_model}"
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _provider_for(self, model: str) -> BaseProvider:
        tier = self._model_to_tier.get(model, "TIER_1")
        return self._tier_providers[tier]

    def _check_airgap(self) -> None:
        if self.settings.mode == "airgapped":
            raise EgressBlockedError(
                "LLM unavailable: MODE=airgapped. "
                "Use /api/eligibility/check for deterministic answers."
            )

    def _resolve_params(self, max_tokens: Optional[int]) -> Tuple[int, float]:
        max_tok = max_tokens or self.settings.llm_max_tokens
        temperature = 0.0 if self.settings.secure_mode else self.settings.llm_temperature
        return max_tok, temperature

    # ── Public API (identical signature to original client.py) ────────────────

    async def generate(
        self,
        messages: list,
        model: str,
        system_prompt: str = "",
        max_tokens: int = None,
    ) -> Tuple[str, GenerationMetadata]:
        """
        Non-streaming generation. Returns (text, GenerationMetadata).
        Dispatches to the provider assigned to the tier that owns `model`.
        """
        self._check_airgap()
        max_tok, temperature = self._resolve_params(max_tokens)
        log.info(f"LLM call: model={model}, messages={len(messages)}, max_tokens={max_tok}")
        provider = self._provider_for(model)
        return await provider.generate(messages, model, system_prompt, max_tok, temperature)

    async def stream(
        self,
        messages: list,
        model: str,
        system_prompt: str = "",
        max_tokens: int = None,
    ) -> AsyncGenerator:
        """
        Streaming generation. Returns an async generator that yields text
        chunks followed by a GenerationMetadata sentinel as the last item.
        Caller detects sentinel via isinstance(chunk, GenerationMetadata).
        """
        self._check_airgap()
        max_tok, temperature = self._resolve_params(max_tokens)
        log.info(f"LLM stream: model={model}")
        provider = self._provider_for(model)
        return provider.stream_impl(messages, model, system_prompt, max_tok, temperature)

    async def health_check(self) -> bool:
        """Verify primary (Tier 1) provider connectivity. Returns False when airgapped."""
        if self.settings.mode == "airgapped":
            return False  # LLM intentionally disabled — not an error
        provider = self._tier_providers["TIER_1"]
        return await provider.health_check(self.settings.llm_tier1_model)
