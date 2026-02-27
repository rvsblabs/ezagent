"""Tests for Agent event logging integration using mock LLM and ToolManager."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ezagent.agent import Agent, AgentResult
from ezagent.config import AgentConfig
from ezagent.event_log import EventLogger
from ezagent.llm.base import LLMProvider, LLMResponse, ToolCall


# ---------------------------------------------------------------------------
# Helpers / Mocks
# ---------------------------------------------------------------------------

class MockLLM(LLMProvider):
    """LLM that returns a preset sequence of responses."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = iter(responses)

    async def chat(self, messages, system="", tools=None) -> LLMResponse:
        return next(self._responses)


def _rows(db_path: Path, table: str) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


def _make_logger(tmp_path: Path) -> tuple[EventLogger, Path]:
    db_path = tmp_path / ".ezagent" / "events.db"
    el = EventLogger()
    el.setup(db_path)
    return el, db_path


def _make_agent(
    llm: LLMProvider,
    event_logger: Optional[EventLogger] = None,
    agent_runner=None,
) -> Agent:
    config = AgentConfig(description="test agent")
    agent = Agent(
        name="test",
        config=config,
        project_dir=Path("/tmp"),
        provider=llm,
        agent_names=[],
        agent_runner=agent_runner,
        event_logger=event_logger,
    )
    # Skip initialize() — no tool manager needed for these tests
    return agent


import asyncio


# ---------------------------------------------------------------------------
# Basic run logging
# ---------------------------------------------------------------------------

async def test_successful_run_creates_agent_run_row(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    llm = MockLLM([LLMResponse(text="hello back", tool_calls=[], stop_reason="end_turn")])
    agent = _make_agent(llm, event_logger=el)

    result = await agent.run("hello")

    await asyncio.sleep(0.05)  # flush fire-and-forget

    assert result.text == "hello back"
    rows = _rows(db_path, "agent_runs")
    assert len(rows) == 1
    r = rows[0]
    assert r["agent_name"] == "test"
    assert r["input_message"] == "hello"
    assert r["status"] == "success"
    assert r["output_text"] == "hello back"
    assert r["duration_ms"] is not None
    assert r["source"] == "manual"
    assert r["depth"] == 0


async def test_run_logs_source_and_parent(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn")])
    agent = _make_agent(llm, event_logger=el)

    await agent.run("do it", source="delegation", parent_run_uuid="parent-uuid-123")
    await asyncio.sleep(0.05)

    r = _rows(db_path, "agent_runs")[0]
    assert r["source"] == "delegation"
    assert r["parent_run_uuid"] == "parent-uuid-123"


async def test_failed_run_logs_error_status(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)

    class FailingLLM(LLMProvider):
        async def chat(self, messages, system="", tools=None) -> LLMResponse:
            raise RuntimeError("API timeout")

    agent = _make_agent(FailingLLM(), event_logger=el)

    with pytest.raises(RuntimeError, match="API timeout"):
        await agent.run("hello")

    await asyncio.sleep(0.05)

    rows = _rows(db_path, "agent_runs")
    assert len(rows) == 1
    r = rows[0]
    assert r["status"] == "error"
    assert "API timeout" in r["error_message"]


# ---------------------------------------------------------------------------
# LLM call logging
# ---------------------------------------------------------------------------

async def test_single_llm_call_logged(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    llm = MockLLM([LLMResponse(text="done", tool_calls=[], stop_reason="end_turn")])
    agent = _make_agent(llm, event_logger=el)

    await agent.run("question")
    await asyncio.sleep(0.05)

    rows = _rows(db_path, "llm_calls")
    assert len(rows) == 1
    r = rows[0]
    assert r["call_number"] == 1
    assert r["output_text"] == "done"
    assert r["stop_reason"] == "end_turn"
    assert r["tool_calls_json"] is None
    assert r["duration_ms"] is not None


async def test_multiple_llm_calls_logged(tmp_path: Path):
    """Two LLM calls: first returns a tool call, second returns final text."""
    el, db_path = _make_logger(tmp_path)

    fake_tool_call = ToolCall(id="tc1", name="use_skill", input={"name": "myskill"})
    responses = [
        LLMResponse(text="", tool_calls=[fake_tool_call], stop_reason="tool_use"),
        LLMResponse(text="final answer", tool_calls=[], stop_reason="end_turn"),
    ]
    llm = MockLLM(responses)

    config = AgentConfig(description="test")
    agent = Agent(
        name="test",
        config=config,
        project_dir=Path("/tmp"),
        provider=llm,
        agent_names=[],
        event_logger=el,
    )
    # Manually populate skill content so use_skill works without ToolManager
    agent._skill_contents = {"myskill": "skill content here"}
    agent._skill_descriptions = {"myskill": "my skill desc"}

    await agent.run("use myskill")
    await asyncio.sleep(0.05)

    rows = _rows(db_path, "llm_calls")
    assert len(rows) == 2
    call_numbers = {r["call_number"] for r in rows}
    assert call_numbers == {1, 2}

    first = next(r for r in rows if r["call_number"] == 1)
    assert first["stop_reason"] == "tool_use"
    assert first["tool_calls_json"] is not None
    parsed = json.loads(first["tool_calls_json"])
    assert parsed[0]["name"] == "use_skill"


async def test_llm_call_links_to_agent_run(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn")])
    agent = _make_agent(llm, event_logger=el)

    await agent.run("q")
    await asyncio.sleep(0.05)

    run_uuid = _rows(db_path, "agent_runs")[0]["run_uuid"]
    llm_run_uuid = _rows(db_path, "llm_calls")[0]["run_uuid"]
    assert run_uuid == llm_run_uuid


# ---------------------------------------------------------------------------
# Tool call logging
# ---------------------------------------------------------------------------

async def test_mcp_tool_call_logged(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)

    fake_tc = ToolCall(id="tc1", name="myprebuilt_tool", input={"key": "val"})
    responses = [
        LLMResponse(text="", tool_calls=[fake_tc], stop_reason="tool_use"),
        LLMResponse(text="done", tool_calls=[], stop_reason="end_turn"),
    ]
    llm = MockLLM(responses)

    config = AgentConfig(description="test")
    agent = Agent(
        name="test",
        config=config,
        project_dir=Path("/tmp"),
        provider=llm,
        agent_names=[],
        event_logger=el,
    )

    # Mock the ToolManager so call_tool returns a string
    mock_tm = MagicMock()
    mock_tm.get_tool_schemas.return_value = [
        {
            "name": "myprebuilt_tool",
            "description": "a tool",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    mock_tm.is_agent_tool.return_value = None
    mock_tm.call_tool = AsyncMock(return_value="tool result")
    agent._tool_manager = mock_tm

    await agent.run("use the tool")
    await asyncio.sleep(0.05)

    rows = _rows(db_path, "tool_invocations")
    assert len(rows) == 1
    r = rows[0]
    assert r["tool_name"] == "myprebuilt_tool"
    assert r["input_json"] == json.dumps({"key": "val"})
    assert r["status"] == "success"
    assert r["output_text"] == "tool result"
    assert r["duration_ms"] is not None


async def test_tool_call_links_to_agent_run(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)

    fake_tc = ToolCall(id="tc1", name="t", input={})
    llm = MockLLM([
        LLMResponse(text="", tool_calls=[fake_tc], stop_reason="tool_use"),
        LLMResponse(text="done", tool_calls=[], stop_reason="end_turn"),
    ])
    config = AgentConfig(description="test")
    agent = Agent(
        name="test",
        config=config,
        project_dir=Path("/tmp"),
        provider=llm,
        agent_names=[],
        event_logger=el,
    )
    mock_tm = MagicMock()
    mock_tm.get_tool_schemas.return_value = []
    mock_tm.is_agent_tool.return_value = None
    mock_tm.call_tool = AsyncMock(return_value="r")
    agent._tool_manager = mock_tm

    await agent.run("go")
    await asyncio.sleep(0.05)

    run_uuid = _rows(db_path, "agent_runs")[0]["run_uuid"]
    tool_run_uuid = _rows(db_path, "tool_invocations")[0]["run_uuid"]
    assert run_uuid == tool_run_uuid


# ---------------------------------------------------------------------------
# Agent delegation logging
# ---------------------------------------------------------------------------

async def test_delegation_passes_source_and_parent_uuid(tmp_path: Path):
    """When agent A delegates to agent B, agent B's run should have
    source='delegation' and parent_run_uuid set to A's run_uuid."""
    el, db_path = _make_logger(tmp_path)

    # Agent A will call agent_b tool
    fake_tc = ToolCall(id="tc1", name="agent_b", input={"message": "subquery"})
    llm_a = MockLLM([
        LLMResponse(text="", tool_calls=[fake_tc], stop_reason="tool_use"),
        LLMResponse(text="final", tool_calls=[], stop_reason="end_turn"),
    ])
    llm_b = MockLLM([LLMResponse(text="sub-answer", tool_calls=[], stop_reason="end_turn")])

    config_a = AgentConfig(description="agent a", tools=["agent_b"])
    config_b = AgentConfig(description="agent b")

    agent_b = Agent(
        name="b",
        config=config_b,
        project_dir=Path("/tmp"),
        provider=llm_b,
        agent_names=["b"],
        event_logger=el,
    )

    async def runner(name, msg, depth, debug, source="delegation", parent_run_uuid=None):
        return await agent_b.run(
            msg, depth=depth, debug=debug,
            source=source, parent_run_uuid=parent_run_uuid,
        )

    agent_a = Agent(
        name="a",
        config=config_a,
        project_dir=Path("/tmp"),
        provider=llm_a,
        agent_names=["b"],
        agent_runner=runner,
        event_logger=el,
    )

    # Mock ToolManager for agent A so it recognises "agent_b" as an agent tool
    mock_tm = MagicMock()
    mock_tm.get_tool_schemas.return_value = []
    mock_tm.is_agent_tool.side_effect = lambda name: "b" if name == "agent_b" else None
    agent_a._tool_manager = mock_tm

    await agent_a.run("do it", source="manual")
    await asyncio.sleep(0.05)

    rows = {r["agent_name"]: r for r in _rows(db_path, "agent_runs")}
    assert "a" in rows
    assert "b" in rows
    assert rows["a"]["source"] == "manual"
    assert rows["b"]["source"] == "delegation"
    assert rows["b"]["parent_run_uuid"] == rows["a"]["run_uuid"]


# ---------------------------------------------------------------------------
# No event_logger — agent still works fine
# ---------------------------------------------------------------------------

async def test_agent_works_without_event_logger():
    llm = MockLLM([LLMResponse(text="ok", tool_calls=[], stop_reason="end_turn")])
    agent = _make_agent(llm, event_logger=None)
    result = await agent.run("hello")
    assert result.text == "ok"


async def test_agent_run_depth_exceeded_no_logger():
    llm = MockLLM([])
    agent = _make_agent(llm, event_logger=None)
    result = await agent.run("deep", depth=10)
    assert "Maximum agent recursion depth" in result.text
