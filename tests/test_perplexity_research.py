"""Tests for Perplexity research tool (Responses API)."""

import json
import os
from unittest.mock import patch

import pytest


def test_perplexity_research_requires_api_key():
    """perplexity_research returns error if PERPLEXITY_API_KEY is not set."""
    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": ""}, clear=False):
        from ezagent.tools.builtins.perplexity_research.main import _perplexity_research_impl

        result = _perplexity_research_impl("What is AI?", preset="fast-search")
        data = json.loads(result)
        assert "error" in data
        assert "PERPLEXITY_API_KEY" in data["error"]


def test_perplexity_research_calls_responses_api_with_preset():
    """perplexity_research calls /v1/responses with correct preset."""
    mock_response = {
        "output": [
            {
                "content": [{"text": "AI is artificial intelligence.", "type": "output_text"}],
                "role": "assistant",
                "status": "completed",
            }
        ]
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        with patch("ezagent.tools.builtins.perplexity_research.main.requests.post") as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None

            from ezagent.tools.builtins.perplexity_research.main import _perplexity_research_impl

            result = _perplexity_research_impl("What is AI?", preset="pro-search")

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "v1/responses" in call_args[0][0]
    assert call_args[1]["json"]["preset"] == "pro-search"
    assert call_args[1]["json"]["input"] == "What is AI?"
    assert call_args[1]["json"]["stream"] is False

    data = json.loads(result)
    assert "output_text" in data
    assert "AI is artificial intelligence" in data["output_text"]


def test_perplexity_research_supports_all_presets():
    """perplexity_research accepts fast-search, pro-search, deep-research, advanced-deep-research."""
    presets = ["fast-search", "pro-search", "deep-research", "advanced-deep-research"]
    mock_response = {
        "output": [
            {
                "content": [{"text": "Test response.", "type": "output_text"}],
                "role": "assistant",
                "status": "completed",
            }
        ]
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        with patch("ezagent.tools.builtins.perplexity_research.main.requests.post") as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None

            from ezagent.tools.builtins.perplexity_research.main import _perplexity_research_impl

            for preset in presets:
                _perplexity_research_impl("query", preset=preset)
                assert mock_post.call_args[1]["json"]["preset"] == preset


def test_perplexity_research_handles_empty_output():
    """perplexity_research handles malformed or empty API response."""
    mock_response = {"output": []}

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        with patch("ezagent.tools.builtins.perplexity_research.main.requests.post") as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None

            from ezagent.tools.builtins.perplexity_research.main import _perplexity_research_impl

            result = _perplexity_research_impl("query", preset="fast-search")

    data = json.loads(result)
    assert "output_text" in data
    assert data["output_text"] == ""
