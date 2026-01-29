from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from ezagent.config import AgentConfig
from ezagent.llm.base import LLMProvider, LLMResponse
from ezagent.tools.manager import ToolManager

MAX_RECURSION_DEPTH = 10
MAX_DEBUG_RESULT_LENGTH = 200


@dataclass
class AgentResult:
    """Result of an agent run, including optional debug events."""

    text: str
    debug_events: List[str] = field(default_factory=list)


class Agent:
    """Core agent: loads skills into system prompt, runs agentic tool-use loop."""

    def __init__(
        self,
        name: str,
        config: AgentConfig,
        project_dir: Path,
        provider: LLMProvider,
        agent_names: List[str],
        agent_runner: Optional[
            Callable[[str, str, int, bool], Coroutine[Any, Any, "AgentResult"]]
        ] = None,
    ):
        self.name = name
        self.config = config
        self.project_dir = project_dir
        self.provider = provider
        self.agent_names = agent_names
        self._agent_runner = agent_runner
        self._tool_manager: Optional[ToolManager] = None
        self._system_prompt: str = ""

    async def initialize(self):
        """Load skills and connect to MCP tools."""
        # Build system prompt from description + skills
        parts = []
        if self.config.description:
            parts.append(f"You are: {self.config.description}")

        skills_dir = self.project_dir / "skills"
        for skill in self.config.skills:
            skill_path = skills_dir / f"{skill}.md"
            if skill_path.is_file():
                content = skill_path.read_text().strip()
                parts.append(f"## Skill: {skill}\n{content}")

        self._system_prompt = "\n\n".join(parts)

        # Connect tool manager
        self._tool_manager = ToolManager(
            self.project_dir, self.config.tools, self.agent_names
        )
        await self._tool_manager.connect()

    async def run(
        self, message: str, depth: int = 0, debug: bool = False
    ) -> AgentResult:
        """Run the agentic loop: send message, handle tool calls, repeat."""
        debug_events: List[str] = []

        if depth >= MAX_RECURSION_DEPTH:
            return AgentResult(
                text=f"[Error: Maximum agent recursion depth ({MAX_RECURSION_DEPTH}) reached]",
                debug_events=debug_events,
            )

        if debug:
            loaded_skills = ", ".join(self.config.skills) if self.config.skills else "(none)"
            debug_events.append(f"[{self.name}] Skills loaded: {loaded_skills}")

        tools = self._tool_manager.get_tool_schemas() if self._tool_manager else []
        messages: List[Dict[str, Any]] = [{"role": "user", "content": message}]

        while True:
            if debug:
                debug_events.append(f"[{self.name}] Calling LLM...")

            response: LLMResponse = await self.provider.chat(
                messages=messages,
                system=self._system_prompt,
                tools=tools if tools else None,
            )

            # If no tool calls, return the text response
            if not response.tool_calls:
                return AgentResult(text=response.text, debug_events=debug_events)

            # Build assistant message with all content blocks
            assistant_content: List[Dict[str, Any]] = []
            if response.text:
                assistant_content.append({"type": "text", "text": response.text})
            for tc in response.tool_calls:
                assistant_content.append(
                    {
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.input,
                    }
                )
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call and collect results
            tool_results: List[Dict[str, Any]] = []
            for tc in response.tool_calls:
                if debug:
                    debug_events.append(
                        f"[{self.name}] Tool call: {tc.name}({json.dumps(tc.input)})"
                    )

                result_text = await self._execute_tool(
                    tc.name, tc.input, depth, debug, debug_events
                )

                if debug:
                    truncated = result_text[:MAX_DEBUG_RESULT_LENGTH]
                    if len(result_text) > MAX_DEBUG_RESULT_LENGTH:
                        truncated += "..."
                    debug_events.append(f"[{self.name}] Tool result: {truncated}")

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result_text,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

    async def _execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        depth: int,
        debug: bool = False,
        debug_events: List[str] | None = None,
    ) -> str:
        """Execute a tool call — either MCP tool or agent-as-tool delegation."""
        if self._tool_manager is None:
            return json.dumps({"error": "Tool manager not initialized"})

        # Check if this is an agent-as-tool
        delegated_agent = self._tool_manager.is_agent_tool(tool_name)
        if delegated_agent is not None:
            if self._agent_runner is None:
                return json.dumps({"error": "Agent delegation not available"})
            agent_message = arguments.get("message", "")
            if debug and debug_events is not None:
                debug_events.append(
                    f"[{self.name}] Delegating to agent '{delegated_agent}' with message: {agent_message}"
                )
            result = await self._agent_runner(
                delegated_agent, agent_message, depth + 1, debug
            )
            # Merge debug events from delegated agent
            if debug and debug_events is not None and isinstance(result, AgentResult):
                debug_events.extend(result.debug_events)
                return result.text
            if isinstance(result, AgentResult):
                return result.text
            return result

        return await self._tool_manager.call_tool(tool_name, arguments)

    async def shutdown(self):
        """Disconnect all tool clients."""
        if self._tool_manager:
            await self._tool_manager.disconnect()
