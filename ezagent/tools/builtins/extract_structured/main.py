"""Prebuilt extract_structured tool for ezagent.

Extracts structured data from text using Perplexity's Chat Completions API
with JSON Schema response_format. Use for entity extraction, form filling,
or any structured output from unstructured text.

Requires PERPLEXITY_API_KEY.
"""

from __future__ import annotations

import json
import os

import requests
from fastmcp import FastMCP

mcp = FastMCP("extract_structured")

API_URL = "https://api.perplexity.ai/chat/completions"

def _extract_json_from_content(content: str) -> dict | None:
    """Extract a JSON object from content that may include reasoning text."""
    content = content.strip()
    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Find {...} by brace matching (reasoning models may prefix text)
    start = content.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(content[start:], start=start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(content[start : i + 1])
                except json.JSONDecodeError:
                    pass
    return None


def _extract_structured_impl(text: str, json_schema: dict) -> str:
    """Core logic for extract_structured. Callable from tests."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return json.dumps(
            {
                "error": "PERPLEXITY_API_KEY environment variable is not set. "
                "Get an API key at https://docs.perplexity.ai/"
            }
        )

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Perplexity uses OpenAI-compatible response_format with json_schema
        payload = {
            "model": "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": "Extract structured data from the user's text according to the provided JSON schema. Return only valid JSON matching the schema, with no extra explanation.",
                },
                {"role": "user", "content": text},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "extraction_result",
                    "strict": True,
                    "schema": json_schema,
                },
            },
            "max_tokens": 4096,
        }
        resp = requests.post(
            API_URL,
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        extracted = _extract_json_from_content(content)
        if extracted is None:
            return json.dumps(
                {"error": f"Could not parse JSON from model response: {content[:200]}..."}
            )
        return json.dumps({"extracted": extracted})
    except requests.RequestException as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def extract_structured(text: str, json_schema: dict) -> str:
    """Extract structured data from text using Perplexity's JSON Schema extraction.

    The model returns JSON matching your schema. Useful for entity extraction,
    form filling, or converting unstructured text to structured data.

    Args:
        text: The unstructured text to extract from.
        json_schema: A JSON Schema dict (e.g. {"type": "object", "properties": {...}}).
    """
    return _extract_structured_impl(text, json_schema)


if __name__ == "__main__":
    mcp.run()
