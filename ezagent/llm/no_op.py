"""LLM provider for agents that never call the model (provider: none)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ezagent.llm.base import LLMProvider, LLMResponse


class NoOpLLMProvider(LLMProvider):
    """Placeholder provider for tool-only agents. Must not be used for chat()."""

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        raise RuntimeError(
            "NoOpLLMProvider.chat() was called; agent with provider 'none' "
            "must only use the tool pipeline, not the LLM loop."
        )
