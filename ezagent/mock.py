"""Mock mode: replay pre-recorded fixtures instead of live APIs."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ezagent.agent import Agent
from ezagent.config import ProjectConfig
from ezagent.llm.base import LLMProvider, LLMResponse, ToolCall


class FixtureLLMProvider(LLMProvider):
    """Replays LLM responses in order from fixture data."""

    def __init__(self, responses: List[Dict[str, Any]]):
        self._responses = responses
        self._index = 0

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system: str = "",
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> LLMResponse:
        if self._index >= len(self._responses):
            raise IndexError(
                f"FixtureLLMProvider: no more responses "
                f"(requested index {self._index}, have {len(self._responses)})"
            )
        response_data = self._responses[self._index]
        self._index += 1
        tool_calls = []
        for i, tc in enumerate(response_data.get("tool_calls") or []):
            tool_calls.append(
                ToolCall(
                    id=tc.get("id", f"fixture_tc_{i}"),
                    name=tc["name"],
                    input=tc.get("input", {}),
                )
            )
        return LLMResponse(
            text=response_data.get("text", ""),
            tool_calls=tool_calls,
            stop_reason=response_data.get("stop_reason", "end_turn"),
        )


class FixtureToolManager:
    """Replays tool outputs in order per tool_name. No MCP processes."""

    def __init__(self, tool_calls: Dict[str, List[str]]):
        self._tool_calls = {k: list(v) for k, v in tool_calls.items()}
        self._counters: Dict[str, int] = {}

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        idx = self._counters.get(name, 0)
        calls = self._tool_calls.get(name, [])
        if idx >= len(calls):
            raise IndexError(
                f"FixtureToolManager: no more outputs for tool '{name}' "
                f"(requested index {idx}, have {len(calls)})"
            )
        self._counters[name] = idx + 1
        return calls[idx]

    def is_agent_tool(self, tool_name: str) -> Optional[str]:
        return None

    async def disconnect(self):
        pass


def load_fixture(path: Path) -> Dict[str, Any]:
    """Load a fixture YAML file."""
    with open(path) as f:
        return yaml.safe_load(f)


def _setup_agent_for_mock(
    agent: Agent, fixture: Dict[str, Any], project_dir: Path
) -> None:
    """Set up agent with fixture providers, bypassing initialize().

    Replicates the skill-loading portion of Agent.initialize() but
    skips MCP connection entirely.
    """
    parts = []
    if agent.config.description:
        parts.append(f"You are: {agent.config.description}")

    skills_dir = project_dir / "skills"
    for skill in agent.config.skills:
        if skill in agent._external_skill_paths:
            skill_path = agent._external_skill_paths[skill] / "skill.md"
        else:
            skill_path = skills_dir / f"{skill}.md"
        if skill_path.is_file():
            content = skill_path.read_text().strip()
            agent._skill_contents[skill] = content
            description = ""
            for line in content.splitlines():
                stripped = line.strip().lstrip("#").strip()
                if stripped:
                    description = stripped
                    break
            agent._skill_descriptions[skill] = description or skill

    if agent._skill_contents:
        skill_lines = [
            f"- {name}: {desc}"
            for name, desc in agent._skill_descriptions.items()
        ]
        parts.append(
            "You have access to the following skills. "
            "Call the `use_skill` tool to load full instructions for a skill before using it.\n"
            + "\n".join(skill_lines)
        )

    agent._system_prompt = "\n\n".join(parts)

    # Normalize tool_calls: {tool_name: [{output: ...}, ...]} -> {tool_name: [str, ...]}
    raw_tool_calls = fixture.get("tool_calls") or {}
    normalized: Dict[str, List[str]] = {}
    for k, v in raw_tool_calls.items():
        outputs = []
        for item in v:
            if isinstance(item, dict):
                outputs.append(str(item.get("output", "")))
            else:
                outputs.append(str(item))
        normalized[k] = outputs

    agent._tool_manager = FixtureToolManager(normalized)


async def _run_async(
    agent_name: str,
    message: str,
    fixture_path: Path,
    project_dir: Path,
    config: ProjectConfig,
    debug: bool,
) -> str:
    fixture = load_fixture(fixture_path)
    agent_config = config.agents[agent_name]
    llm_responses = fixture.get("llm_calls") or []
    provider = FixtureLLMProvider(llm_responses)

    agent = Agent(
        name=agent_name,
        config=agent_config,
        project_dir=project_dir,
        provider=provider,
        agent_names=list(config.agents.keys()),
    )
    _setup_agent_for_mock(agent, fixture, project_dir)
    result = await agent.run(message, debug=debug)
    return result.text


def run_with_fixture(
    agent_name: str,
    message: str,
    fixture_path: Path,
    project_dir: Path,
    config: ProjectConfig,
    debug: bool,
) -> str:
    """Sync wrapper used by CLI."""
    return asyncio.run(
        _run_async(agent_name, message, fixture_path, project_dir, config, debug)
    )
