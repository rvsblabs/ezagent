"""Tests for custom tool descriptions (scaffold template and API)."""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def test_tool_template_includes_module_docstring():
    """Scaffolded tools have a module docstring for descriptions."""
    from ezagent.scaffold import TOOL_TEMPLATE

    rendered = TOOL_TEMPLATE.format(name="greeter")
    assert '"""greeter tool -' in rendered or "greeter" in rendered
    assert "Customize this docstring" in rendered


def test_create_tool_produces_main_py_with_docstring():
    """create_tool produces main.py with a module-level docstring."""
    from ezagent.scaffold import create_tool

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        create_tool("my_tool", base)
        main_py = base / "my_tool" / "main.py"
        content = main_py.read_text()
        assert content.startswith('"""')
        assert "my_tool" in content
        # Docstring is extractable
        import ast

        tree = ast.parse(content)
        doc = ast.get_docstring(tree)
        assert doc is not None
        assert "my_tool" in doc


def test_get_tools_returns_local_tools_with_descriptions():
    """GET /v1/tools returns local tools as {name, description} objects."""
    from ezagent.config import ProjectConfig
    from ezagent.server import create_app

    with tempfile.TemporaryDirectory() as tmp:
        project_dir = Path(tmp)
        # Minimal agents.yml (one agent, no tools)
        (project_dir / "agents.yml").write_text(
            """
agents:
  assistant:
    tools: ""
    skills: ""
    description: "Test"
"""
        )
        # Custom tool with docstring
        tool_dir = project_dir / "tools" / "greeter"
        tool_dir.mkdir(parents=True)
        (tool_dir / "main.py").write_text(
            '''"""Greeter tool - Greets users by name."""

from fastmcp import FastMCP

mcp = FastMCP("greeter")

@mcp.tool()
def greet(name: str) -> str:
    """Greet someone by name."""
    return f"Hello, {name}!"

if __name__ == "__main__":
    mcp.run()
'''
        )
        config = ProjectConfig(
            agents={"assistant": {"tools": "greeter", "skills": "", "description": "Test"}},
            project_dir=project_dir,
        )
        # Need to create skills dir and file since agent references greeter as tool
        (project_dir / "skills").mkdir(exist_ok=True)
        (project_dir / "skills" / "friendly.md").write_text("# friendly\n")
        # Fix: use greeter as tool, need empty skills
        config = ProjectConfig(
            agents={"assistant": {"tools": "greeter", "skills": "", "description": "Test"}},
            project_dir=project_dir,
        )
        # Actually the validator will check skills - we need a valid skill or empty
        # Let me simplify - agent with no skills
        (project_dir / "skills" / "dummy.md").write_text("dummy")
        config = ProjectConfig(
            agents={
                "assistant": {
                    "tools": "greeter",
                    "skills": "dummy",
                    "description": "Test",
                }
            },
            project_dir=project_dir,
        )

        app = create_app(config)
        client = TestClient(app)
        resp = client.get("/v1/tools")

    assert resp.status_code == 200
    data = resp.json()
    assert "prebuilt" in data
    assert "local" in data
    assert isinstance(data["local"], list)
    local = data["local"]
    assert len(local) >= 1
    greeter = next((t for t in local if t["name"] == "greeter"), None)
    assert greeter is not None
    assert greeter["description"] == "Greeter tool - Greets users by name."
