"""Tests for PlanAndDelegateRuntime orchestration."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ezagent.agent import Agent, AgentResult
from ezagent.config import OrchestrationConfig
from ezagent.orchestration import PlanAndDelegateRuntime
from ezagent.llm.base import LLMResponse


@pytest.fixture
def mock_planner_response():
    """Planner returns JSON task list."""
    return [
        {"agent": "researcher", "message": "Research topic A"},
        {"agent": "writer", "message": "Write summary of A"},
    ]


@pytest.fixture
def mock_agents():
    """Mock agent instances."""
    researcher = MagicMock(spec=Agent)
    researcher.run = AsyncMock(return_value=AgentResult(text="Researched A"))
    writer = MagicMock(spec=Agent)
    writer.run = AsyncMock(return_value=AgentResult(text="Written summary"))
    return {"researcher": researcher, "writer": writer, "planner": researcher}


@pytest.fixture
def orch_config():
    return OrchestrationConfig(
        pattern="plan_and_delegate",
        planner="planner",
        workers=["researcher", "writer"],
        aggregator="writer",
        parallel=True,
    )


@pytest.fixture
def mock_planner_provider(mock_planner_response):
    """LLM provider that returns parsed task list as if planner produced it."""
    provider = MagicMock()
    tasks_json = json.dumps(mock_planner_response)
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            text=f'```json\n{tasks_json}\n```',
            tool_calls=[],
            stop_reason="end_turn",
        )
    )
    return provider


@pytest.mark.asyncio
async def test_plan_and_delegate_runs_workers_in_parallel(
    orch_config, mock_agents, mock_planner_provider, mock_planner_response
):
    """Runtime calls planner, gets tasks, runs workers in parallel, aggregates."""
    runtime = PlanAndDelegateRuntime(
        name="research_flow",
        config=orch_config,
        agents=mock_agents,
        planner_provider=mock_planner_provider,
        event_logger=None,
    )

    result = await runtime.run("Research AI safety and write a report")

    # Planner was called once with planning prompt
    assert mock_planner_provider.chat.await_count == 1
    call_args = mock_planner_provider.chat.await_args
    messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
    assert messages is not None
    assert any("Research AI safety" in str(m) for m in messages)

    # Workers were invoked (parallel via gather)
    mock_agents["researcher"].run.assert_awaited_once()
    mock_agents["writer"].run.assert_awaited()

    # Aggregator (writer) was called with worker results
    writer_calls = mock_agents["writer"].run.await_args_list
    # First calls are from worker tasks, last may be aggregator
    assert len(writer_calls) >= 1

    assert result.text
    assert "Written" in result.text or "Researched" in result.text


@pytest.mark.asyncio
async def test_plan_and_delegate_handles_empty_tasks(orch_config, mock_agents):
    """When planner returns empty task list, runtime handles gracefully."""
    provider = MagicMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            text="[]",
            tool_calls=[],
            stop_reason="end_turn",
        )
    )

    runtime = PlanAndDelegateRuntime(
        name="flow",
        config=orch_config,
        agents=mock_agents,
        planner_provider=provider,
        event_logger=None,
    )

    result = await runtime.run("Do nothing")

    # No worker runs
    mock_agents["researcher"].run.assert_not_awaited()
    # Aggregator still called with empty results (or we return early)
    assert result.text is not None


@pytest.mark.asyncio
async def test_plan_and_delegate_invalid_json_fallback(orch_config, mock_agents):
    """When planner returns invalid JSON, runtime handles without crashing."""
    provider = MagicMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            text="This is not JSON at all",
            tool_calls=[],
            stop_reason="end_turn",
        )
    )

    runtime = PlanAndDelegateRuntime(
        name="flow",
        config=orch_config,
        agents=mock_agents,
        planner_provider=provider,
        event_logger=None,
    )

    result = await runtime.run("Something")
    # Should not raise; returns something
    assert result is not None
    assert hasattr(result, "text")
