"""Dataset-based evaluation of agent outputs."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import yaml

from ezagent.config import ProjectConfig


@dataclass
class EvalCase:
    id: str
    input: str
    expected: str
    scorer: str = "substring"
    fixture: Optional[str] = None  # path to fixture YAML (mock mode if provided)


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    output: str
    expected: str
    scorer: str
    error: Optional[str] = None


def load_eval_dataset(path: Path) -> Tuple[str, List[EvalCase]]:
    """Load an eval YAML file. Returns (agent_name, cases)."""
    with open(path) as f:
        raw = yaml.safe_load(f)
    agent_name = raw["agent"]
    cases = [
        EvalCase(
            id=case_data["id"],
            input=case_data["input"],
            expected=case_data["expected"],
            scorer=case_data.get("scorer", "substring"),
            fixture=case_data.get("fixture"),
        )
        for case_data in raw.get("cases", [])
    ]
    return agent_name, cases


def score(output: str, expected: str, scorer: str) -> bool:
    """Score an output against an expected value using the given scorer."""
    if scorer == "exact":
        return output.strip() == expected.strip()
    elif scorer == "regex":
        return bool(re.search(expected, output, re.IGNORECASE))
    else:  # substring (default)
        return expected in output


async def _live_run_async(
    agent_name: str, message: str, config: ProjectConfig, debug: bool
) -> str:
    """Run agent live (no fixture, no recording)."""
    from ezagent.agent import Agent
    from ezagent.llm import create_provider

    agent_config = config.agents[agent_name]
    provider_name = agent_config.provider or config.provider
    model = agent_config.model or config.model
    provider = create_provider(provider_name, model)

    agent = Agent(
        name=agent_name,
        config=agent_config,
        project_dir=config.project_dir,
        provider=provider,
        agent_names=list(config.agents.keys()),
    )
    await agent.initialize()
    try:
        result = await agent.run(message, debug=debug)
        return result.text
    finally:
        await agent.shutdown()


async def run_eval_async(
    eval_path: Path,
    config: ProjectConfig,
    debug: bool,
) -> List[EvalResult]:
    agent_name, cases = load_eval_dataset(eval_path)
    results = []
    for case in cases:
        try:
            if case.fixture:
                from ezagent.mock import _run_async as mock_run

                fixture_path = eval_path.parent / case.fixture
                output = await mock_run(
                    agent_name,
                    case.input,
                    fixture_path,
                    config.project_dir,
                    config,
                    debug,
                )
            else:
                output = await _live_run_async(agent_name, case.input, config, debug)
        except Exception as exc:
            results.append(
                EvalResult(
                    case_id=case.id,
                    passed=False,
                    output="",
                    expected=case.expected,
                    scorer=case.scorer,
                    error=str(exc),
                )
            )
            continue

        passed = score(output, case.expected, case.scorer)
        results.append(
            EvalResult(
                case_id=case.id,
                passed=passed,
                output=output,
                expected=case.expected,
                scorer=case.scorer,
            )
        )
    return results


def run_eval(eval_path: Path, config: ProjectConfig, debug: bool) -> List[EvalResult]:
    """Synchronous wrapper used by CLI."""
    return asyncio.run(run_eval_async(eval_path, config, debug))
