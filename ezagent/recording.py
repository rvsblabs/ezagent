"""Fixture recording: capture a live run to YAML for later replay."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ezagent.agent import Agent
from ezagent.config import ProjectConfig
from ezagent.llm.base import LLMProvider, LLMResponse
from ezagent.tools.manager import ToolManager


class RecordingLLMProvider(LLMProvider):
    """Wraps a real LLMProvider and records all responses."""

    def __init__(self, real: LLMProvider):
        self._real = real
        self.recorded: List[Dict[str, Any]] = []

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        response = await self._real.chat(messages, system, tools)
        self.recorded.append(
            {
                "text": response.text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in response.tool_calls
                ],
                "stop_reason": response.stop_reason,
            }
        )
        return response


class RecordingToolManager:
    """Wraps a real ToolManager and records all tool outputs."""

    def __init__(self, real: ToolManager):
        self._real = real
        self.recorded: List[Dict[str, Any]] = []

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return self._real.get_tool_schemas()

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        output = await self._real.call_tool(name, arguments)
        self.recorded.append({"tool_name": name, "input": arguments, "output": output})
        return output

    def is_agent_tool(self, tool_name: str) -> Optional[str]:
        return self._real.is_agent_tool(tool_name)

    async def disconnect(self):
        await self._real.disconnect()


def save_fixture(
    path: Path,
    agent_name: str,
    message: str,
    llm_calls: List[Dict[str, Any]],
    tool_calls: List[Dict[str, Any]],
) -> None:
    """Serialize recorded calls to YAML fixture file."""
    # Group tool calls by tool_name, preserving call order within each name
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for call in tool_calls:
        name = call["tool_name"]
        if name not in grouped:
            grouped[name] = []
        grouped[name].append({"output": call["output"]})

    fixture = {
        "agent": agent_name,
        "input": message,
        "llm_calls": llm_calls,
        "tool_calls": grouped,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(fixture, f, default_flow_style=False, allow_unicode=True)


async def _run_async(
    agent_name: str,
    message: str,
    output_path: Path,
    project_dir: Path,
    config: ProjectConfig,
    debug: bool,
) -> str:
    from ezagent.llm import create_provider

    agent_config = config.agents[agent_name]
    provider_name = agent_config.provider or config.provider
    model = agent_config.model or config.model
    provider = create_provider(provider_name, model)

    agent = Agent(
        name=agent_name,
        config=agent_config,
        project_dir=project_dir,
        provider=provider,
        agent_names=list(config.agents.keys()),
    )
    await agent.initialize()

    recording_provider = RecordingLLMProvider(agent.provider)
    recording_tool_manager = RecordingToolManager(agent._tool_manager)
    agent.provider = recording_provider
    agent._tool_manager = recording_tool_manager

    try:
        result = await agent.run(message, debug=debug)
    finally:
        await agent.shutdown()

    save_fixture(
        output_path,
        agent_name,
        message,
        recording_provider.recorded,
        recording_tool_manager.recorded,
    )
    return result.text


def run_with_recording(
    agent_name: str,
    message: str,
    output_path: Path,
    project_dir: Path,
    config: ProjectConfig,
    debug: bool,
) -> str:
    """Sync wrapper used by CLI."""
    return asyncio.run(
        _run_async(agent_name, message, output_path, project_dir, config, debug)
    )
