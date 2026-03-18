"""Tests for tool-only agents (provider='none') with pre_tools/run_tools pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import asyncio
import json

import pytest

from ezagent.agent import Agent, AgentResult
from ezagent.config import AgentConfig
from ezagent.event_log import EventLogger


class DummyProvider:
    """LLMProvider-like dummy used for provider='none' agents.

    Tool-only agents must never call chat() on this provider.
    """

    async def chat(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover - should not be called
        raise RuntimeError("Tool-only agent must not call chat()")


def _make_logger(tmp_path: Path) -> tuple[EventLogger, Path]:
    db_path = tmp_path / ".ezagent" / "events.db"
    el = EventLogger()
    el.setup(db_path)
    return el, db_path


def _rows(db_path: Path, table: str) -> list[Dict[str, Any]]:
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_tool_only_agent_runs_pipeline_and_logs(tmp_path: Path):
    """provider='none' agents should execute pre_tools/run_tools without calling LLM."""
    el, db_path = _make_logger(tmp_path)

    # Configure a simple pipeline: fetch_news -> store_articles
    config = AgentConfig(
        description="tool-only news ingestor",
        provider="none",
        tools=["retrieve_news", "store_articles"],
    )
    # Attach pipeline attributes expected by the runtime; config schema
    # validation is handled separately in config tests.
    config.pre_tools = [
        {
            "id": "fetch_news",
            "tool": "retrieve_news",
            "args": {"category": "tech"},
            "as": "raw_news",
        }
    ]
    config.run_tools = [
        {
            "tool": "store_articles",
            "args_from": "raw_news",
        }
    ]

    agent = Agent(
        name="news_ingestor",
        config=config,
        project_dir=tmp_path,
        provider=DummyProvider(),  # must never be used
        agent_names=[],
        event_logger=el,
    )

    # Inject a fake ToolManager with deterministic behavior
    mock_tm = MagicMock()
    mock_tm.get_tool_schemas.return_value = []
    mock_tm.is_agent_tool.return_value = None

    async def fake_call_tool(name: str, arguments: Dict[str, Any]) -> str:
        if name == "retrieve_news":
            # Return JSON string representing fetched items
            return json.dumps([{"title": "Item 1"}, {"title": "Item 2"}])
        if name == "store_articles":
            # Assert that the second tool receives the first tool's JSON output
            assert arguments == {"items": [{"title": "Item 1"}, {"title": "Item 2"}]}
            return "stored 2"
        raise AssertionError(f"Unexpected tool call: {name}")

    mock_tm.call_tool = AsyncMock(side_effect=fake_call_tool)
    agent._tool_manager = mock_tm

    result: AgentResult = await agent.run("ingest tech news", source="scheduled")
    await asyncio.sleep(0.05)

    # Agent result should come from the final tool in the pipeline
    assert result.text == "stored 2"

    # Agent run should be logged with source='scheduled'
    runs = _rows(db_path, "agent_runs")
    assert len(runs) == 1
    r = runs[0]
    assert r["agent_name"] == "news_ingestor"
    assert r["source"] == "scheduled"
    assert r["status"] == "success"
    assert r["output_text"] == "stored 2"

