"""OpenAI LLM provider."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from .base import LLMProvider
from ._openai_compat import convert_messages, convert_tools, parse_response


class OpenAIProvider(LLMProvider):
    """Provider for OpenAI models (GPT-4o, GPT-4o-mini, etc.)."""

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model: str = DEFAULT_MODEL):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY environment variable is not set. "
                "Set it before starting the daemon."
            )
        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        openai_messages = convert_messages(messages, system)
        openai_tools = convert_tools(tools) if tools else None

        # o-series and newer reasoning models only accept max_completion_tokens
        token_param = (
            "max_completion_tokens"
            if self.model.split("-")[0] in {"o1", "o3", "o4", "o5", "gpt5"}
            or self.model.startswith("o1")
            or self.model.startswith("o3")
            or self.model.startswith("o4")
            else "max_tokens"
        )
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            token_param: 4096,
        }
        if openai_tools:
            kwargs["tools"] = openai_tools

        response = await self.client.chat.completions.create(**kwargs)
        return parse_response(response)
