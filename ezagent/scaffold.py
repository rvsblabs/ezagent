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


TOOL_TEMPLATE = """\
from fastmcp import FastMCP

mcp = FastMCP("{name}")


@mcp.tool()
def hello(text: str) -> str:
    \"\"\"A sample tool function.\"\"\"
    return f"[{name}] Received: {{text}}"


if __name__ == "__main__":
    mcp.run()
"""

TOOL_REQUIREMENTS = """\
# Add Python dependencies for this tool here, one per line.
"""

SKILL_TEMPLATE = """\
# {name}
Describe what this skill does and how the agent should behave.
"""


def create_tool(name: str, base_dir: Path) -> Path:
    """Scaffold a new tool directory with main.py and requirements.txt.

    Creates <base_dir>/<name>/main.py and <base_dir>/<name>/requirements.txt.
    """
    tool_dir = base_dir / name
    if tool_dir.exists():
        raise FileExistsError(f"Tool directory already exists: {tool_dir}")

    tool_dir.mkdir(parents=True)
    (tool_dir / "main.py").write_text(TOOL_TEMPLATE.format(name=name))
    (tool_dir / "requirements.txt").write_text(TOOL_REQUIREMENTS)
    return tool_dir


def create_skill(name: str, base_dir: Path) -> Path:
    """Scaffold a new skill markdown file.

    Creates <base_dir>/<name>.md.
    """
    base_dir.mkdir(parents=True, exist_ok=True)
    skill_path = base_dir / f"{name}.md"
    if skill_path.exists():
        raise FileExistsError(f"Skill file already exists: {skill_path}")

    skill_path.write_text(SKILL_TEMPLATE.format(name=name))
    return skill_path


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
