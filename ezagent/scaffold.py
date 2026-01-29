from pathlib import Path

EXAMPLE_AGENTS_YML = """\
# ezagent configuration
# Define your agents, their tools, and skills here.
#
# agents:
#   my_agent:
#     tools: tool_name, other_agent_name
#     skills: skill_name
#     description: "What this agent does"
#
# Tools live in tools/<tool_name>/main.py (FastMCP servers)
# Skills live in skills/<skill_name>.md (markdown instructions)

agents:
  assistant:
    tools: greeter
    skills: friendly
    description: "A friendly assistant that can greet people by name"
"""

EXAMPLE_TOOL = """\
from fastmcp import FastMCP

mcp = FastMCP("greeter")


@mcp.tool()
def greet(name: str) -> str:
    \"\"\"Greet someone by name.\"\"\"
    return f"Hello, {name}! Welcome to ezagent."


if __name__ == "__main__":
    mcp.run()
"""

EXAMPLE_SKILL = """\
You are a friendly and helpful assistant.
When someone introduces themselves, use the greet tool to welcome them by name.
Keep your responses concise and helpful.
"""


def create_project(app_name: str) -> Path:
    """Scaffold a new ezagent project directory."""
    base = Path.cwd() / app_name

    if base.exists():
        raise FileExistsError(f"Directory '{app_name}' already exists.")

    tools_dir = base / "tools"
    skills_dir = base / "skills"

    # Create sample tool
    greeter_dir = tools_dir / "greeter"
    greeter_dir.mkdir(parents=True)
    (greeter_dir / "main.py").write_text(EXAMPLE_TOOL)

    # Create sample skill
    skills_dir.mkdir(parents=True)
    (skills_dir / "friendly.md").write_text(EXAMPLE_SKILL)

    # Create agents.yml wired to the sample tool and skill
    (base / "agents.yml").write_text(EXAMPLE_AGENTS_YML)

    return base
