"""Tests for orchestration config validation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from ezagent.config import load_config, ProjectConfig


def _make_project_dir(agents_yml: str, skills: dict[str, str] | None = None) -> Path:
    """Create a minimal project dir with agents.yml and required skills."""
    d = Path(tempfile.mkdtemp())
    (d / "agents.yml").write_text(agents_yml)
    skills_dir = d / "skills"
    skills_dir.mkdir()
    for name, content in (skills or {"friendly": "Be friendly"}).items():
        (skills_dir / f"{name}.md").write_text(content)
    tools_dir = d / "tools"
    tools_dir.mkdir()
    greeter = tools_dir / "greeter"
    greeter.mkdir()
    (greeter / "main.py").write_text('from fastmcp import FastMCP\nmcp = FastMCP("x")\n@mcp.tool()\ndef x(): pass\nif __name__ == "__main__": mcp.run()')
    return d


def test_load_config_with_orchestrations():
    """Config loads orchestrations and validates them."""
    yml = """
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
"""
    d = _make_project_dir(yml, {"planning": "Plan tasks", "friendly": "Be friendly"})
    cfg = load_config(d)
    assert "orchestrations" in dir(cfg)
    orch = cfg.orchestrations["research_flow"]
    assert orch.pattern == "plan_and_delegate"
    assert orch.planner == "planner"
    assert orch.workers == ["researcher", "writer"]
    assert orch.aggregator == "writer"
    assert orch.parallel is True


def test_orchestration_invalid_pattern_rejected():
    """Invalid pattern raises ValueError."""
    yml = """
orchestrations:
  bad:
    pattern: invalid_pattern
    planner: planner
    workers: [researcher]
    aggregator: researcher

agents:
  planner:
    tools: researcher
    skills: planning
    description: Plans
  researcher:
    tools: greeter
    skills: friendly
    description: Researches
"""
    d = _make_project_dir(yml, {"planning": "x", "friendly": "x"})
    with pytest.raises(ValueError, match="invalid_pattern|pattern"):
        load_config(d)


def test_orchestration_unknown_planner_rejected():
    """Orchestration referencing unknown planner raises ValueError."""
    yml = """
orchestrations:
  flow:
    pattern: plan_and_delegate
    planner: nonexistent
    workers: [researcher]
    aggregator: researcher

agents:
  researcher:
    tools: greeter
    skills: friendly
    description: Researches
"""
    d = _make_project_dir(yml, {"friendly": "x"})
    with pytest.raises(ValueError, match="planner|nonexistent"):
        load_config(d)


def test_orchestration_unknown_worker_rejected():
    """Orchestration referencing unknown worker raises ValueError."""
    yml = """
orchestrations:
  flow:
    pattern: plan_and_delegate
    planner: planner
    workers: [bad_worker]
    aggregator: planner

agents:
  planner:
    tools: greeter
    skills: friendly
    description: Plans
"""
    d = _make_project_dir(yml, {"friendly": "x"})
    with pytest.raises(ValueError, match="worker|bad_worker"):
        load_config(d)


def test_orchestration_unknown_aggregator_rejected():
    """Orchestration referencing unknown aggregator raises ValueError."""
    yml = """
orchestrations:
  flow:
    pattern: plan_and_delegate
    planner: planner
    workers: [researcher]
    aggregator: nobody

agents:
  planner:
    tools: researcher
    skills: friendly
    description: Plans
  researcher:
    tools: greeter
    skills: friendly
    description: Researches
"""
    d = _make_project_dir(yml, {"friendly": "x"})
    with pytest.raises(ValueError, match="aggregator|nobody"):
        load_config(d)


def test_agent_can_list_orchestration_as_tool():
    """Agent can list an orchestration name in tools (like discussions)."""
    yml = """
orchestrations:
  flow:
    pattern: plan_and_delegate
    planner: planner
    workers: [worker]
    aggregator: planner

agents:
  entry:
    tools: flow
    skills: friendly
    description: Entry point that runs orchestration
  planner:
    tools: worker
    skills: friendly
    description: Plans
  worker:
    tools: greeter
    skills: friendly
    description: Worker
"""
    d = _make_project_dir(yml, {"friendly": "x"})
    cfg = load_config(d)
    assert "flow" in cfg.agents["entry"].tools
