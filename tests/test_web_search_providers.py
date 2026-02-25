"""Tests for web search providers (Brave, Perplexity)."""

import os
from unittest.mock import patch

import pytest


def test_perplexity_search_provider_requires_api_key():
    """PerplexitySearchProvider raises if PERPLEXITY_API_KEY is not set."""
    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": ""}, clear=False):
        from ezagent.tools.builtins.web_search.main import PerplexitySearchProvider

        with pytest.raises(RuntimeError, match="PERPLEXITY_API_KEY"):
            PerplexitySearchProvider()


def test_perplexity_search_provider_returns_mapped_results():
    """PerplexitySearchProvider maps API response to title, url, snippet format."""
    mock_response = {
        "results": [
            {
                "title": "Python 3.13 Release",
                "url": "https://python.org/release",
                "snippet": "Python 3.13 introduces new features.",
            },
            {
                "title": "Another Result",
                "url": "https://example.com",
                "snippet": "Some description here.",
            },
        ],
        "id": "search-123",
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        from ezagent.tools.builtins.web_search.main import PerplexitySearchProvider

        provider = PerplexitySearchProvider()

    with patch("ezagent.tools.builtins.web_search.main.requests.post") as mock_post:
        mock_resp = mock_post.return_value
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = lambda: None

        results = provider.search("python 3.13", count=5)

    assert len(results) == 2
    assert results[0]["title"] == "Python 3.13 Release"
    assert results[0]["url"] == "https://python.org/release"
    assert results[0]["snippet"] == "Python 3.13 introduces new features."
    assert results[1]["title"] == "Another Result"
    assert results[1]["url"] == "https://example.com"


def test_perplexity_search_provider_respects_count():
    """PerplexitySearchProvider limits results to requested count."""
    mock_response = {
        "results": [
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "snippet": "Snippet"}
            for i in range(10)
        ],
        "id": "search-456",
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        from ezagent.tools.builtins.web_search.main import PerplexitySearchProvider

        provider = PerplexitySearchProvider()

    with patch("ezagent.tools.builtins.web_search.main.requests.post") as mock_post:
        mock_resp = mock_post.return_value
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status = lambda: None

        results = provider.search("test query", count=3)

    assert len(results) == 3
    mock_post.assert_called_once()
    # Verify max_results was passed
    call_kwargs = mock_post.call_args[1]
    assert call_kwargs["json"]["max_results"] == 3
