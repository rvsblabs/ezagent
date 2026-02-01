from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from .base import LLMProvider, LLMResponse, ToolCall


class GoogleProvider(LLMProvider):
    def __init__(self, model: str = "gemini-2.0-flash"):
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Set it before starting the daemon."
            )
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        gemini_contents = _convert_messages(messages)
        gemini_tools = _convert_tools(tools) if tools else None

        config: Dict[str, Any] = {}
        if system:
            config["system_instruction"] = system
        if gemini_tools:
            config["tools"] = gemini_tools

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=gemini_contents,
            config=types.GenerateContentConfig(**config) if config else None,
        )

        return _parse_response(response)


def _convert_tools(
    tools: List[Dict[str, Any]],
) -> List[types.Tool]:
    declarations = []
    for tool in tools:
        params = tool.get("input_schema")
        if params:
            # Remove the top-level $schema key if present — Gemini doesn't accept it
            params = {k: v for k, v in params.items() if k != "$schema"}
        declarations.append(
            types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=params,
            )
        )
    return [types.Tool(function_declarations=declarations)]


def _convert_messages(
    messages: List[Dict[str, Any]],
) -> List[types.Content]:
    contents: List[types.Content] = []
    for msg in messages:
        role = msg["role"]
        # Gemini uses "user" and "model" roles
        gemini_role = "model" if role == "assistant" else "user"
        content = msg["content"]

        if isinstance(content, str):
            contents.append(
                types.Content(
                    role=gemini_role,
                    parts=[types.Part.from_text(text=content)],
                )
            )
        elif isinstance(content, list):
            parts: List[types.Part] = []
            for block in content:
                if block.get("type") == "text":
                    parts.append(types.Part.from_text(text=block["text"]))
                elif block.get("type") == "tool_use":
                    parts.append(
                        types.Part.from_function_call(
                            name=block["name"],
                            args=block.get("input", {}),
                        )
                    )
                elif block.get("type") == "tool_result":
                    result_content = block.get("content", "")
                    parts.append(
                        types.Part.from_function_response(
                            name=block.get("name", block.get("tool_use_id", "unknown")),
                            response={"result": result_content},
                        )
                    )
            if parts:
                contents.append(
                    types.Content(role=gemini_role, parts=parts)
                )
    return contents


def _parse_response(response: Any) -> LLMResponse:
    text_parts: List[str] = []
    tool_calls: List[ToolCall] = []

    if not response.candidates:
        return LLMResponse(text="", tool_calls=[], stop_reason="end_turn")

    candidate = response.candidates[0]
    for part in candidate.content.parts:
        if part.text is not None:
            text_parts.append(part.text)
        elif part.function_call is not None:
            fc = part.function_call
            tool_calls.append(
                ToolCall(
                    id=f"toolu_{uuid.uuid4().hex[:24]}",
                    name=fc.name,
                    input=dict(fc.args) if fc.args else {},
                )
            )

    stop_reason = "end_turn"
    if tool_calls:
        stop_reason = "tool_use"

    return LLMResponse(
        text="\n".join(text_parts),
        tool_calls=tool_calls,
        stop_reason=stop_reason,
    )
