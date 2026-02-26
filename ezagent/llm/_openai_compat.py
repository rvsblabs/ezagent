"""Shared helpers for OpenAI-compatible API clients (OpenAI, DeepSeek)."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .base import LLMResponse, ToolCall


def convert_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Anthropic-format tools to OpenAI format."""
    result = []
    for tool in tools:
        params = tool.get("input_schema") or {"type": "object", "properties": {}}
        params = {k: v for k, v in params.items() if k != "$schema"}
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": params,
            },
        })
    return result


def convert_messages(
    messages: List[Dict[str, Any]],
    system: str,
) -> List[Dict[str, Any]]:
    """Convert Anthropic-format messages to OpenAI format."""
    result: List[Dict[str, Any]] = []

    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if role == "system":
            if result and result[-1]["role"] == "system":
                result[-1]["content"] = (
                    str(result[-1]["content"]) + "\n\n" + str(content)
                )
            elif not result:
                result.append({"role": "system", "content": content})
            continue

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            text_parts = []
            tool_calls: List[Dict[str, Any]] = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": block.get("name", ""),
                            "arguments": _json_args(block.get("input", {})),
                        },
                    })
                elif block.get("type") == "tool_result":
                    result.append({
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id", ""),
                        "content": block.get("content", ""),
                    })
            if tool_calls or text_parts:
                if tool_calls:
                    result.append({
                        "role": "assistant",
                        "content": "\n".join(text_parts) if text_parts else None,
                        "tool_calls": tool_calls,
                    })
                elif text_parts:
                    result.append({
                        "role": role,
                        "content": "\n".join(text_parts),
                    })
            continue

    return result


def _json_args(obj: Dict[str, Any]) -> str:
    return json.dumps(obj) if obj else "{}"


def parse_response(response: Any) -> LLMResponse:
    """Parse OpenAI-style response into LLMResponse."""
    if not response.choices:
        return LLMResponse(text="", tool_calls=[], stop_reason="end_turn")

    choice = response.choices[0]
    message = choice.message
    text = message.content or ""

    tool_calls: List[ToolCall] = []
    if message.tool_calls:
        for tc in message.tool_calls:
            if tc.function:
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(
                    ToolCall(
                        id=tc.id or "",
                        name=tc.function.name or "",
                        input=args,
                    )
                )

    stop_reason = "end_turn"
    if tool_calls:
        stop_reason = "tool_use"

    return LLMResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=stop_reason,
    )
