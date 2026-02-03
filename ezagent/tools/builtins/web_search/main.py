"""Prebuilt web search tool for ezagent.

Provides web search and page reading via a pluggable provider abstraction.
Default provider: Brave Search API (requires BRAVE_SEARCH_API_KEY env var).
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Optional

import requests
from fastmcp import FastMCP

mcp = FastMCP("web_search")

# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------

_provider_instance: Optional[SearchProvider] = None


class SearchProvider(ABC):
    """Abstract base class for web search providers."""

    @abstractmethod
    def search(self, query: str, count: int) -> list[dict]:
        """Search the web and return a list of result dicts.

        Each dict must contain: title, url, snippet.
        """
        ...


class BraveSearchProvider(SearchProvider):
    """Brave Search API provider.

    Requires the BRAVE_SEARCH_API_KEY environment variable.
    """

    API_URL = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self) -> None:
        self.api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "BRAVE_SEARCH_API_KEY environment variable is not set. "
                "Get a free API key at https://brave.com/search/api/"
            )

    def search(self, query: str, count: int) -> list[dict]:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": self.api_key,
        }
        params = {"q": query, "count": min(count, 20)}
        resp = requests.get(self.API_URL, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                }
            )
        return results[:count]


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDERS: dict[str, type[SearchProvider]] = {
    "brave": BraveSearchProvider,
}


def _get_provider() -> SearchProvider:
    """Get (or create) the configured search provider."""
    global _provider_instance
    if _provider_instance is None:
        name = os.environ.get("WEB_SEARCH_PROVIDER", "brave").lower()
        cls = _PROVIDERS.get(name)
        if cls is None:
            available = ", ".join(sorted(_PROVIDERS.keys()))
            raise RuntimeError(
                f"Unknown web search provider '{name}'. Available: {available}"
            )
        _provider_instance = cls()
    return _provider_instance


# ---------------------------------------------------------------------------
# HTML stripping helper
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

MAX_PAGE_CHARS = 20_000


def _strip_html(html: str) -> str:
    """Crude HTML-to-text: remove tags and collapse whitespace."""
    text = _TAG_RE.sub(" ", html)
    text = _WS_RE.sub(" ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def web_search(query: str, count: int = 5) -> str:
    """Search the web for a query and return results.

    Args:
        query: The search query string.
        count: Number of results to return (default 5, max 20).
    """
    try:
        provider = _get_provider()
        results = provider.search(query, count)
        return json.dumps({"results": results, "count": len(results)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def web_search_read(url: str) -> str:
    """Fetch a URL and return its text content (HTML stripped).

    Useful for reading the full content of a page found via web_search.
    Content is truncated to ~20,000 characters.

    Args:
        url: The URL to fetch.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ezagent/1.0)",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        text = _strip_html(resp.text)
        if len(text) > MAX_PAGE_CHARS:
            text = text[:MAX_PAGE_CHARS] + "\n\n[Content truncated]"
        return json.dumps({"url": url, "content": text})
    except Exception as e:
        return json.dumps({"error": str(e), "url": url})


if __name__ == "__main__":
    mcp.run()
