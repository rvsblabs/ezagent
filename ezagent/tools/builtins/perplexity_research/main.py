"""Prebuilt Perplexity research tool for ezagent.

Calls Perplexity Responses API (/v1/responses) with presets:
- fast-search: Quick answers (1 step)
- pro-search: Balanced research (3 steps)
- deep-research: In-depth analysis (10 steps)
- advanced-deep-research: Institutional-grade research (10 steps)

Requires PERPLEXITY_API_KEY.
"""

from __future__ import annotations

import json
import os

import requests
from fastmcp import FastMCP

mcp = FastMCP("perplexity_research")

API_URL = "https://api.perplexity.ai/v1/responses"

_VALID_PRESETS = frozenset(
    {"fast-search", "pro-search", "deep-research", "advanced-deep-research"}
)


def _extract_output_text(data: dict) -> str:
    """Extract aggregated text from Responses API output structure."""
    output = data.get("output", [])
    parts = []
    for item in output:
        for content in item.get("content", []):
            if content.get("type") == "output_text" and "text" in content:
                parts.append(content["text"])
    return "".join(parts)


def _perplexity_research_impl(query: str, preset: str = "pro-search") -> str:
    """Core logic for perplexity_research. Callable from tests."""
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return json.dumps(
            {
                "error": "PERPLEXITY_API_KEY environment variable is not set. "
                "Get an API key at https://docs.perplexity.ai/"
            }
        )

    preset = preset.lower().strip()
    if preset not in _VALID_PRESETS:
        return json.dumps(
            {
                "error": f"Invalid preset '{preset}'. "
                f"Valid: {', '.join(sorted(_VALID_PRESETS))}"
            }
        )

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "input": query,
            "preset": preset,
            "stream": False,
        }
        resp = requests.post(
            API_URL,
            headers=headers,
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        output_text = _extract_output_text(data)
        return json.dumps({"output_text": output_text})
    except requests.RequestException as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def perplexity_research(
    query: str,
    preset: str = "pro-search",
) -> str:
    """Run Perplexity research on a query using the Responses API.

    Uses different presets for varying depth:
    - fast-search: Quick answers (~1 step, fastest)
    - pro-search: Balanced research (~3 steps)
    - deep-research: In-depth analysis (~10 steps, 2-4 min)
    - advanced-deep-research: Institutional-grade (~10 steps)

    Args:
        query: The research question or topic to investigate.
        preset: One of fast-search, pro-search, deep-research, advanced-deep-research.
    """
    return _perplexity_research_impl(query, preset)


if __name__ == "__main__":
    mcp.run()
