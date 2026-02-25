"""Tests for Perplexity extract_structured tool."""

import json
import os
from unittest.mock import patch

import pytest


def test_extract_structured_requires_api_key():
    """extract_structured returns error if PERPLEXITY_API_KEY is not set."""
    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": ""}, clear=False):
        from ezagent.tools.builtins.extract_structured.main import _extract_structured_impl

        schema = {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
            "required": ["name", "age"],
        }
        result = _extract_structured_impl("John is 30 years old.", schema)
        data = json.loads(result)
        assert "error" in data
        assert "PERPLEXITY_API_KEY" in data["error"]


def test_extract_structured_calls_chat_completions_with_schema():
    """extract_structured calls chat/completions with response_format json_schema."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": '{"name": "John", "age": 30}',
                }
            }
        ]
    }

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
        "required": ["name", "age"],
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        with patch(
            "ezagent.tools.builtins.extract_structured.main.requests.post"
        ) as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None

            from ezagent.tools.builtins.extract_structured.main import _extract_structured_impl

            result = _extract_structured_impl("John is 30 years old.", schema)

    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "chat/completions" in call_args[0][0]
    body = call_args[1]["json"]
    assert body["model"] == "sonar"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == schema
    assert any(
        "John is 30 years old" in str(m.get("content", ""))
        for m in body["messages"]
        if m.get("role") == "user"
    )

    data = json.loads(result)
    assert data["extracted"] == {"name": "John", "age": 30}


def test_extract_structured_handles_invalid_json_in_response():
    """extract_structured handles model returning non-JSON or malformed content."""
    mock_response = {
        "choices": [
            {
                "message": {
                    "content": "Here is the reasoning... {\"name\": \"John\", \"age\": 30}",
                }
            }
        ]
    }

    schema = {
        "type": "object",
        "properties": {"name": {"type": "string"}, "age": {"type": "integer"}},
    }

    with patch.dict(os.environ, {"PERPLEXITY_API_KEY": "test-key"}):
        with patch(
            "ezagent.tools.builtins.extract_structured.main.requests.post"
        ) as mock_post:
            mock_resp = mock_post.return_value
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = lambda: None

            from ezagent.tools.builtins.extract_structured.main import _extract_structured_impl

            result = _extract_structured_impl("John is 30.", schema)

    data = json.loads(result)
    assert "extracted" in data or "error" in data
    if "extracted" in data:
        assert data["extracted"].get("name") == "John"
