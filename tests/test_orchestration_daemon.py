"""Tests for daemon orchestration integration: run orchestration via socket."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ezagent.config import load_config
from ezagent.daemon import AgentDaemon
from ezagent.llm.base import LLMResponse


def _make_mock_provider():
    """Mock LLM provider that avoids API calls."""
    provider = MagicMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            text="",
            tool_calls=[],
            stop_reason="end_turn",
        )
    )
    return provider


def _make_orchestration_project() -> Path:
    """Create a minimal project with an orchestration."""
    d = Path(tempfile.mkdtemp())
    (d / "agents.yml").write_text("""
provider: anthropic
model: claude-sonnet-4-20250514

orchestrations:
  research_flow:
    pattern: plan_and_delegate
    planner: planner
    workers: [researcher, writer]
    aggregator: writer
    parallel: true

agents:
  planner:
    tools: researcher, writer
    skills: planning
    description: Plans tasks
  researcher:
    tools: greeter
    skills: friendly
    description: Researches
  writer:
    tools: greeter
    skills: friendly
    description: Writes
""")
    (d / "skills").mkdir(parents=True)
    (d / "skills" / "planning.md").write_text("Decompose requests into tasks.")
    (d / "skills" / "friendly.md").write_text("Be helpful.")
    (d / "tools" / "greeter").mkdir(parents=True)
    (d / "tools" / "greeter" / "main.py").write_text('''
from fastmcp import FastMCP
mcp = FastMCP("greeter")
@mcp.tool()
def greet(name: str) -> str:
    return f"Hello, {name}"
if __name__ == "__main__":
    mcp.run()
''')
    return d


@pytest.mark.asyncio
@patch("ezagent.daemon.create_provider", return_value=_make_mock_provider())
async def test_daemon_creates_orchestration_runtimes(mock_create_provider):
    """Daemon creates orchestration runtimes."""
    project_dir = _make_orchestration_project()
    cfg = load_config(project_dir)
    assert "research_flow" in cfg.orchestrations

    daemon = AgentDaemon(cfg)
    await daemon.initialize()

    assert hasattr(daemon, "_orchestration_runtimes")
    assert "research_flow" in daemon._orchestration_runtimes

    await daemon.shutdown()


@pytest.mark.asyncio
@patch("ezagent.daemon.create_provider", return_value=_make_mock_provider())
async def test_run_orchestration_with_mocked_runtime(mock_create_provider):
    """Run orchestration returns result from runtime (mocked to avoid API calls)."""
    project_dir = _make_orchestration_project()
    cfg = load_config(project_dir)
    daemon = AgentDaemon(cfg)
    await daemon.initialize()

    # Replace runtime with mock
    from ezagent.orchestration import OrchestrationResult

    mock_result = OrchestrationResult(text="Synthesized final answer", tasks=[], worker_results=[])
    daemon._orchestration_runtimes["research_flow"] = MagicMock()
    daemon._orchestration_runtimes["research_flow"].run = AsyncMock(return_value=mock_result)

    result = await daemon._run_orchestration("research_flow", "Summarize the weather")
    assert result["text"] == "Synthesized final answer"
    assert "error" not in result

    await daemon.shutdown()


@pytest.mark.asyncio
@patch("ezagent.daemon.create_provider", return_value=_make_mock_provider())
async def test_planner_agent_has_orchestration_names_when_listed(mock_create_provider):
    """Agent with orchestration in tools gets _orchestration_names."""
    project_dir = _make_orchestration_project()
    # Add entry agent with orchestration as tool to agents.yml
    (project_dir / "agents.yml").write_text("""
provider: anthropic
model: claude-sonnet-4-20250514

orchestrations:
  research_flow:
    pattern: plan_and_delegate
    planner: planner
    workers: [researcher, writer]
    aggregator: writer
    parallel: true

agents:
  entry:
    tools: research_flow
    skills: friendly
    description: Entry that runs orchestration
  planner:
    tools: researcher, writer
    skills: planning
    description: Plans
  researcher:
    tools: greeter
    skills: friendly
    description: Researches
  writer:
    tools: greeter
    skills: friendly
    description: Writes
""")
    cfg = load_config(project_dir)
    daemon = AgentDaemon(cfg)
    await daemon.initialize()

    entry_agent = daemon.agents.get("entry")
    assert entry_agent is not None
    assert "research_flow" in entry_agent._orchestration_names

    await daemon.shutdown()


@pytest.mark.asyncio
@patch("ezagent.daemon.create_provider", return_value=_make_mock_provider())
async def test_run_orchestration_unknown_returns_error(mock_create_provider):
    """Running unknown orchestration returns error dict."""
    project_dir = _make_orchestration_project()
    cfg = load_config(project_dir)
    daemon = AgentDaemon(cfg)
    await daemon.initialize()

    result = await daemon._run_orchestration("nonexistent", "hello")
    assert "error" in result
    assert "nonexistent" in result["error"]

    await daemon.shutdown()
