"""Tests for LLM providers."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ezagent.llm import create_provider


def test_create_provider_deepseek():
    """create_provider returns DeepSeekProvider for 'deepseek'."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
        provider = create_provider("deepseek")
        assert provider is not None
        assert provider.model == "deepseek-chat"


def test_create_provider_deepseek_with_model():
    """create_provider passes model override to DeepSeekProvider."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
        provider = create_provider("deepseek", model="deepseek-reasoner")
        assert provider.model == "deepseek-reasoner"


def test_create_provider_openai():
    """create_provider returns OpenAIProvider for 'openai'."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        provider = create_provider("openai")
        assert provider is not None
        assert provider.model == "gpt-4o"


def test_create_provider_openai_with_model():
    """create_provider passes model override to OpenAIProvider."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        provider = create_provider("openai", model="gpt-4o-mini")
        assert provider.model == "gpt-4o-mini"


def test_create_provider_unknown_raises():
    """create_provider raises for unknown provider."""
    with pytest.raises(ValueError, match="Unknown LLM provider 'foo'"):
        create_provider("foo")


def test_deepseek_provider_requires_api_key():
    """DeepSeekProvider raises if DEEPSEEK_API_KEY is not set."""
    with patch.dict(os.environ, {}, clear=False):
        # Ensure key is absent
        os.environ.pop("DEEPSEEK_API_KEY", None)
        from ezagent.llm.deepseek import DeepSeekProvider

        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            DeepSeekProvider()


def test_openai_provider_requires_api_key():
    """OpenAIProvider raises if OPENAI_API_KEY is not set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OPENAI_API_KEY", None)
        from ezagent.llm.openai import OpenAIProvider

        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            OpenAIProvider()


@pytest.mark.asyncio
async def test_deepseek_provider_chat_text_response():
    """DeepSeekProvider.chat returns LLMResponse from API."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
        from ezagent.llm.deepseek import DeepSeekProvider

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="Hello!",
                    tool_calls=None,
                )
            )
        ]

        provider = DeepSeekProvider()
        provider.client = AsyncMock()
        provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful.",
        )

        assert result.text == "Hello!"
        assert result.tool_calls == []
        assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_deepseek_provider_chat_tool_calls():
    """DeepSeekProvider.chat parses tool_calls from API response."""
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-test"}):
        from ezagent.llm.deepseek import DeepSeekProvider

        mock_tc = MagicMock()
        mock_tc.id = "call_123"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "NYC"}'

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    tool_calls=[mock_tc],
                )
            )
        ]

        provider = DeepSeekProvider()
        provider.client = AsyncMock()
        provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(
            messages=[{"role": "user", "content": "What's the weather in NYC?"}],
            tools=[
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                }
            ],
        )

        assert result.text == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_123"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"city": "NYC"}
        assert result.stop_reason == "tool_use"


@pytest.mark.asyncio
async def test_openai_provider_chat_text_response():
    """OpenAIProvider.chat returns LLMResponse from API."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from ezagent.llm.openai import OpenAIProvider

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content="Hello!",
                    tool_calls=None,
                )
            )
        ]

        provider = OpenAIProvider()
        provider.client = AsyncMock()
        provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(
            messages=[{"role": "user", "content": "Hi"}],
            system="You are helpful.",
        )

        assert result.text == "Hello!"
        assert result.tool_calls == []
        assert result.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_openai_provider_chat_tool_calls():
    """OpenAIProvider.chat parses tool_calls from API response."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
        from ezagent.llm.openai import OpenAIProvider

        mock_tc = MagicMock()
        mock_tc.id = "call_456"
        mock_tc.function = MagicMock()
        mock_tc.function.name = "get_weather"
        mock_tc.function.arguments = '{"city": "NYC"}'

        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=None,
                    tool_calls=[mock_tc],
                )
            )
        ]

        provider = OpenAIProvider()
        provider.client = AsyncMock()
        provider.client.chat.completions.create = AsyncMock(return_value=mock_response)

        result = await provider.chat(
            messages=[{"role": "user", "content": "What's the weather in NYC?"}],
            tools=[
                {
                    "name": "get_weather",
                    "description": "Get weather",
                    "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
                }
            ],
        )

        assert result.text == ""
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "call_456"
        assert result.tool_calls[0].name == "get_weather"
        assert result.tool_calls[0].input == {"city": "NYC"}
        assert result.stop_reason == "tool_use"
