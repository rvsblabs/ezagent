from __future__ import annotations

from .base import LLMProvider, LLMResponse, ToolCall


def create_provider(name: str, model: str = "") -> LLMProvider:
    """Create an LLM provider by name.

    Args:
        name: Provider name ("anthropic" or "google").
        model: Optional model override. Uses provider default if empty.
    """
    if name == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(model=model) if model else AnthropicProvider()
    elif name == "google":
        from .google import GoogleProvider

        return GoogleProvider(model=model) if model else GoogleProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider '{name}'. Supported: anthropic, google"
        )
