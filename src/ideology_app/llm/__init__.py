"""LLM provider abstraction: one typed call, provider chosen by configuration.

``build_provider`` and ``PROVIDERS`` are the only place that branches on the
provider name. To add a provider: write ``<name>_provider.py``, add one entry to
``PROVIDERS`` and one to ``ideology_app.config.DEFAULT_MODELS``.
"""

from collections.abc import Callable

from ideology_app.config import LLMSettings
from ideology_app.llm.anthropic_provider import AnthropicProvider
from ideology_app.llm.base import (
    LLMConfigError,
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResult,
)
from ideology_app.llm.claude_code_provider import ClaudeCodeProvider
from ideology_app.llm.fake import FakeProvider

PROVIDERS: dict[str, Callable[[str], LLMProvider]] = {
    "anthropic": lambda model: AnthropicProvider(model),
    # Local Operator use only: the Operator's Claude Code CLI and subscription.
    "claude_code": lambda model: ClaudeCodeProvider(model),
    "fake": lambda model: FakeProvider(model=model),
}


def build_provider(settings: LLMSettings) -> LLMProvider:
    """Return the provider named by ``settings``.

    No API client is created and no key is read yet. ``claude_code`` runs a
    preflight here (the CLI is on ``PATH`` and logged in to a Claude
    subscription), so a misconfiguration raises ``LLMConfigError`` before any
    database write.
    """
    try:
        factory = PROVIDERS[settings.provider]
    except KeyError:
        supported = ", ".join(sorted(PROVIDERS))
        raise LLMConfigError(
            f"Unknown LLM provider {settings.provider!r}; supported values: {supported}"
        ) from None
    return factory(settings.model)


__all__ = [
    "PROVIDERS",
    "AnthropicProvider",
    "ClaudeCodeProvider",
    "FakeProvider",
    "LLMConfigError",
    "LLMError",
    "LLMOutputError",
    "LLMProvider",
    "LLMProviderError",
    "LLMRequest",
    "LLMResult",
    "build_provider",
]
