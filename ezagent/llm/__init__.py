from __future__ import annotations

from .base import LLMProvider, LLMResponse, ToolCall


def create_provider(name: str, model: str = "") -> LLMProvider:
    """Create an LLM provider by name.

    Args:
        name: Provider name ("anthropic", "google", or "deepseek").
        model: Optional model override. Uses provider default if empty.
    """
    if name == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(model=model) if model else AnthropicProvider()
    elif name == "google":
        from .google import GoogleProvider

        return GoogleProvider(model=model) if model else GoogleProvider()
    elif name == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider(model=model) if model else DeepSeekProvider()
    else:
        raise ValueError(
            f"Unknown LLM provider '{name}'. Supported: anthropic, google, deepseek"
        )
