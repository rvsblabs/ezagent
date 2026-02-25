"""Tests for orchestration CLI and status."""

from pathlib import Path

from click.testing import CliRunner

from ezagent.cli import cli


def test_orchestrate_command_help():
    """ez orchestrate shows help."""
    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrate", "--help"])
    assert result.exit_code == 0
    assert "orchestrate" in result.output
    assert "plan-and-delegate" in result.output or "message" in result.output


def test_status_shows_orchestrations_when_present():
    """ez status displays orchestrations when config has them."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        (Path.cwd() / "agents.yml").write_text("""
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
        (Path.cwd() / "skills").mkdir()
        (Path.cwd() / "skills" / "planning.md").write_text("x")
        (Path.cwd() / "skills" / "friendly.md").write_text("x")
        (Path.cwd() / "tools" / "greeter").mkdir(parents=True)
        (Path.cwd() / "tools" / "greeter" / "main.py").write_text("""
from fastmcp import FastMCP
mcp = FastMCP("x")
@mcp.tool()
def x(): pass
if __name__ == "__main__": mcp.run()
""")
        result = runner.invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "Orchestrations:" in result.output
        assert "research_flow" in result.output
