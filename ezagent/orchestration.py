"""Orchestration runtimes for multi-agent patterns (plan-and-delegate, etc.)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ezagent.config import OrchestrationConfig

if TYPE_CHECKING:
    from ezagent.agent import Agent
    from ezagent.event_log import EventLogger
    from ezagent.llm.base import LLMProvider


@dataclass
class OrchestrationResult:
    """Result of an orchestration run."""

    text: str
    tasks: List[Dict[str, Any]] = ()
    worker_results: List[str] = ()
    status: str = "success"
    error_message: Optional[str] = None


PLANNER_SYSTEM = """You are a task planner. Given a user request, decompose it into independent sub-tasks.
Output a JSON array of objects. Each object must have:
- "agent": the name of the agent to perform the task (must be one of the workers)
- "message": the specific message/instruction for that agent

Example: [{"agent": "researcher", "message": "Find recent papers on X"}, {"agent": "writer", "message": "Summarize the findings"}]

Reply with ONLY the JSON array — no other text. No markdown code fences."""


def _parse_tasks_from_response(text: str, worker_names: List[str]) -> List[Dict[str, Any]]:
    """Extract JSON task list from planner response. Returns empty list on parse failure."""
    if not text or not text.strip():
        return []
    # Strip markdown code fences if present
    cleaned = (
        text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    tasks = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        agent = item.get("agent")
        message = item.get("message", "")
        if agent in worker_names and isinstance(message, str):
            tasks.append({"agent": agent, "message": message})
    return tasks


class PlanAndDelegateRuntime:
    """
    Plan-and-delegate orchestration: planner decomposes request into tasks,
    workers run (optionally in parallel), aggregator synthesizes.
    """

    def __init__(
        self,
        name: str,
        config: OrchestrationConfig,
        agents: Dict[str, "Agent"],
        planner_provider: "LLMProvider",
        event_logger: Optional["EventLogger"] = None,
    ):
        self.name = name
        self.config = config
        self.agents = agents
        self.planner_provider = planner_provider
        self._event_logger = event_logger

    async def run(self, message: str) -> OrchestrationResult:
        """Execute plan-and-delegate: plan → workers (parallel) → aggregate."""
        orch_uuid: Optional[str] = None
        if self._event_logger is not None:
            orch_uuid = await self._event_logger.start_orchestration_run(
                self.name, message
            )

        try:
            result = await self._run_impl(message)
            if self._event_logger is not None and orch_uuid is not None:
                self._event_logger.finish_orchestration_run(
                    orch_uuid,
                    output_text=result.text,
                    status=result.status,
                    error=result.error_message,
                )
            return result
        except Exception as exc:
            if self._event_logger is not None and orch_uuid is not None:
                self._event_logger.finish_orchestration_run(
                    orch_uuid,
                    output_text="",
                    status="error",
                    error=str(exc),
                )
            raise

    async def _run_impl(self, message: str) -> OrchestrationResult:
        """Internal implementation of run (no event logging)."""
        # 1. Planner LLM call
        planner_prompt = (
            f"User request: {message}\n\n"
            f"Available workers: {', '.join(self.config.workers)}\n\n"
            "Decompose into sub-tasks. Output a JSON array of {agent, message} objects."
        )
        test_planner = os.environ.get("EZAGENT_TEST_PLANNER_RESPONSE")
        if test_planner is not None:
            tasks = _parse_tasks_from_response(test_planner, self.config.workers)
        else:
            response = await self.planner_provider.chat(
                messages=[{"role": "user", "content": planner_prompt}],
                system=PLANNER_SYSTEM,
            )
            tasks = _parse_tasks_from_response(response.text, self.config.workers)

        if not tasks:
            aggregator = self.agents.get(self.config.aggregator or self.config.planner)
            if aggregator:
                fallback = await aggregator.run(
                    f"The planner could not decompose this request. "
                    f"Original: {message}. Please respond directly."
                )
                return OrchestrationResult(
                    text=fallback.text,
                    tasks=[],
                    worker_results=[],
                    status="success",
                )
            return OrchestrationResult(
                text="No tasks could be extracted from the planner response.",
                tasks=[],
                worker_results=[],
                status="success",
            )

        # 2. Run workers (parallel if config.parallel)
        async def run_task(t: dict) -> str:
            agent_name = t["agent"]
            msg = t["message"]
            agent = self.agents.get(agent_name)
            if agent is None:
                return json.dumps({"error": f"Agent '{agent_name}' not found"})
            result = await agent.run(msg, source="orchestration")
            return result.text if hasattr(result, "text") else str(result)

        if self.config.parallel:
            import asyncio

            worker_results = await asyncio.gather(*[run_task(t) for t in tasks])
        else:
            worker_results = []
            for t in tasks:
                r = await run_task(t)
                worker_results.append(r)

        test_final = os.environ.get("EZAGENT_TEST_ORCHESTRATION_FINAL")
        if test_final is not None:
            return OrchestrationResult(
                text=test_final,
                tasks=tasks,
                worker_results=list(worker_results),
                status="success",
            )

        # 3. Aggregator synthesizes
        aggregator_name = self.config.aggregator or self.config.planner
        aggregator = self.agents.get(aggregator_name)
        if aggregator is None:
            combined = "\n\n---\n\n".join(
                f"Task {i+1} ({t['agent']}): {r}"
                for i, (t, r) in enumerate(zip(tasks, worker_results))
            )
            return OrchestrationResult(
                text=combined,
                tasks=tasks,
                worker_results=list(worker_results),
                status="success",
            )

        synthesis_prompt = (
            "You are synthesizing the results of parallel worker agents.\n\n"
            "Original user request:\n"
            f"{message}\n\n"
            "Worker results (in order):\n"
        )
        for i, (t, r) in enumerate(zip(tasks, worker_results)):
            synthesis_prompt += f"\n--- Result {i+1} (from {t['agent']}) ---\n{r}\n"

        synthesis_prompt += "\nProvide a clear, coherent final response to the user."

        agg_result = await aggregator.run(synthesis_prompt, source="orchestration")
        final_text = agg_result.text if hasattr(agg_result, "text") else str(agg_result)

        return OrchestrationResult(
            text=final_text,
            tasks=tasks,
            worker_results=list(worker_results),
            status="success",
        )
