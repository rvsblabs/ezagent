"""Tests for mock mode: FixtureLLMProvider, FixtureToolManager, run_with_fixture."""
import asyncio
from pathlib import Path

import pytest
import yaml

from ezagent.mock import (
    FixtureLLMProvider,
    FixtureToolManager,
    _run_async,
    load_fixture,
)


# ---------------------------------------------------------------------------
# FixtureLLMProvider
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_llm_provider_replays_in_order():
    """FixtureLLMProvider returns responses in sequence."""
    responses = [
        {
            "text": "I'll search.",
            "tool_calls": [{"id": "tc1", "name": "web_search", "input": {"query": "test"}}],
            "stop_reason": "tool_use",
        },
        {"text": "Done.", "tool_calls": [], "stop_reason": "end_turn"},
    ]
    provider = FixtureLLMProvider(responses)

    r1 = await provider.chat([{"role": "user", "content": "hello"}])
    assert r1.text == "I'll search."
    assert len(r1.tool_calls) == 1
    assert r1.tool_calls[0].name == "web_search"
    assert r1.tool_calls[0].id == "tc1"
    assert r1.stop_reason == "tool_use"

    r2 = await provider.chat([{"role": "user", "content": "hello"}])
    assert r2.text == "Done."
    assert r2.tool_calls == []
    assert r2.stop_reason == "end_turn"


@pytest.mark.asyncio
async def test_fixture_llm_provider_raises_when_exhausted():
    """FixtureLLMProvider raises IndexError after all responses consumed."""
    provider = FixtureLLMProvider([{"text": "only", "tool_calls": [], "stop_reason": "end_turn"}])
    await provider.chat([])
    with pytest.raises(IndexError, match="no more responses"):
        await provider.chat([])


@pytest.mark.asyncio
async def test_fixture_llm_provider_auto_generates_tool_call_ids():
    """FixtureLLMProvider auto-generates IDs when not specified."""
    provider = FixtureLLMProvider(
        [{"text": "", "tool_calls": [{"name": "foo", "input": {}}], "stop_reason": "tool_use"}]
    )
    r = await provider.chat([])
    assert r.tool_calls[0].id == "fixture_tc_0"


# ---------------------------------------------------------------------------
# FixtureToolManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fixture_tool_manager_replays_per_tool():
    """FixtureToolManager replays outputs in call order per tool_name."""
    manager = FixtureToolManager(
        {
            "search__search": ["result_a", "result_b"],
            "http__get": ["page_content"],
        }
    )
    assert await manager.call_tool("search__search", {}) == "result_a"
    assert await manager.call_tool("search__search", {}) == "result_b"
    assert await manager.call_tool("http__get", {}) == "page_content"


@pytest.mark.asyncio
async def test_fixture_tool_manager_raises_when_exhausted():
    """FixtureToolManager raises IndexError when no more outputs remain."""
    manager = FixtureToolManager({"mytool": ["only_output"]})
    await manager.call_tool("mytool", {})
    with pytest.raises(IndexError, match="no more outputs for tool 'mytool'"):
        await manager.call_tool("mytool", {})


def test_fixture_tool_manager_get_tool_schemas_empty():
    """FixtureToolManager.get_tool_schemas() always returns empty list."""
    assert FixtureToolManager({}).get_tool_schemas() == []


def test_fixture_tool_manager_is_agent_tool_returns_none():
    """FixtureToolManager.is_agent_tool always returns None."""
    assert FixtureToolManager({}).is_agent_tool("agent_foo") is None
    assert FixtureToolManager({}).is_agent_tool("agent_bar") is None


# ---------------------------------------------------------------------------
# load_fixture
# ---------------------------------------------------------------------------


def test_load_fixture(tmp_path):
    """load_fixture parses YAML and returns the dict."""
    fixture_data = {
        "agent": "reporter",
        "input": "hello",
        "llm_calls": [{"text": "Hi!", "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    fixture_file = tmp_path / "test.yml"
    with open(fixture_file, "w") as f:
        yaml.dump(fixture_data, f)

    loaded = load_fixture(fixture_file)
    assert loaded["agent"] == "reporter"
    assert loaded["input"] == "hello"
    assert len(loaded["llm_calls"]) == 1
    assert loaded["llm_calls"][0]["text"] == "Hi!"


# ---------------------------------------------------------------------------
# _run_async (end-to-end mock run)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_async_simple_response(tmp_path):
    """_run_async returns final LLM text for a simple fixture."""
    from ezagent.config import AgentConfig, ProjectConfig

    fixture_data = {
        "agent": "assistant",
        "input": "hello",
        "llm_calls": [{"text": "Hello there!", "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    fixture_file = tmp_path / "hello.yml"
    with open(fixture_file, "w") as f:
        yaml.dump(fixture_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="Test agent")},
        project_dir=tmp_path,
    )
    result = await _run_async("assistant", "hello", fixture_file, tmp_path, config, False)
    assert result == "Hello there!"


@pytest.mark.asyncio
async def test_run_async_with_tool_call(tmp_path):
    """_run_async replays a tool call and continues to final response."""
    from ezagent.config import AgentConfig, ProjectConfig

    fixture_data = {
        "agent": "assistant",
        "input": "search for AI news",
        "llm_calls": [
            {
                "text": "I'll search.",
                "tool_calls": [
                    {"id": "tc1", "name": "ws__search", "input": {"query": "AI news"}}
                ],
                "stop_reason": "tool_use",
            },
            {"text": "Found it!", "tool_calls": [], "stop_reason": "end_turn"},
        ],
        "tool_calls": {
            "ws__search": [{"output": "AI makes breakthrough..."}],
        },
    }
    fixture_file = tmp_path / "search.yml"
    with open(fixture_file, "w") as f:
        yaml.dump(fixture_data, f)

    config = ProjectConfig(
        agents={"assistant": AgentConfig(tools=[], skills=[], description="")},
        project_dir=tmp_path,
    )
    result = await _run_async(
        "assistant", "search for AI news", fixture_file, tmp_path, config, False
    )
    assert result == "Found it!"


@pytest.mark.asyncio
async def test_run_async_with_skill(tmp_path):
    """_run_async loads skill files from disk even in mock mode."""
    from ezagent.config import AgentConfig, ProjectConfig

    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "summarize.md").write_text("# Summarize\nAlways summarize concisely.")

    # The fixture LLM just returns text, no tool calls
    fixture_data = {
        "agent": "writer",
        "input": "summarize this",
        "llm_calls": [{"text": "Summary complete.", "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    fixture_file = tmp_path / "skills_test.yml"
    with open(fixture_file, "w") as f:
        yaml.dump(fixture_data, f)

    config = ProjectConfig(
        agents={"writer": AgentConfig(tools=[], skills=["summarize"], description="Writer")},
        project_dir=tmp_path,
    )
    result = await _run_async(
        "writer", "summarize this", fixture_file, tmp_path, config, False
    )
    assert result == "Summary complete."
