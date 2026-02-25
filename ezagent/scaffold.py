from pathlib import Path

DOCKERFILE = """\
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /project

# uv is provided by the base image — required by the daemon to run tools
# with isolated dependencies (UvStdioTransport)
RUN pip install "ezagent[serve]"

# Bake project files into the image for production builds.
# In development, docker-compose overrides this with a volume mount.
COPY . .

CMD ["ez", "start"]
"""

DOCKER_COMPOSE = """\
# Two-service setup: daemon and api share a Unix socket via ezagent-tmp.
#
# Usage:
#   cp .env.example .env          # fill in your API keys
#   docker compose up --build     # first run
#   docker compose up             # subsequent runs
#
# API is available at http://localhost:7771
#   POST /v1/agents/{name}/run    — send a message
#   GET  /v1/logs                 — view run history
#   WS   /v1/agents/{name}/stream — streaming responses

services:
  daemon:
    build: .
    command: ez start
    volumes:
      - .:/project          # live reload: edit agents.yml/tools/skills without rebuild
      - ezagent-tmp:/tmp    # share Unix socket with api service
    env_file: .env
    restart: unless-stopped

  api:
    build: .
    command: ez serve --host 0.0.0.0 --port 7771
    ports:
      - "7771:7771"
    volumes:
      - .:/project
      - ezagent-tmp:/tmp    # same socket as daemon
    env_file: .env
    depends_on:
      - daemon
    restart: unless-stopped

volumes:
  ezagent-tmp:
"""

DOCKERIGNORE = """\
.env
.ezagent/
__pycache__/
*.pyc
.git/
"""

ENV_EXAMPLE = """\
# Copy this file to .env and fill in your API keys.
# Never commit .env to version control.

ANTHROPIC_API_KEY=sk-ant-...
GOOGLE_API_KEY=                   # only needed for provider: google
BRAVE_SEARCH_API_KEY=             # only needed for web_search with provider=brave (default)
PERPLEXITY_API_KEY=               # web_search (WEB_SEARCH_PROVIDER=perplexity), perplexity_research, extract_structured
"""

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

PROJECT_CLAUDE_MD = """\
# ezagent Project

This is an [ezagent](https://github.com/rvsblabs/ezagent) project.
Agents, tools, and skills are defined in `agents.yml`.

## Project Structure
```
agents.yml          # Agent configuration (edit this to add/configure agents)
tools/              # FastMCP tool servers — one subdirectory per tool
  <tool_name>/
    main.py         # FastMCP server code
    requirements.txt  # Optional Python dependencies (auto-installed by uv)
skills/             # Skill instruction files
  <skill_name>.md   # First non-empty line becomes the skill summary
```

## CLI Commands
```bash
ez start                        # Start daemon (foreground, Ctrl+C to stop)
ez start -d                     # Start daemon in background
ez stop                         # Stop daemon
ez status                       # Show running agents and scheduled tasks
ez <agent> "<message>"          # Send a message to an agent
ez run <agent> "<message>"      # Explicit form of the above
ez --debug <agent> "<message>"  # Show tool calls and LLM steps
ez create tool <name>           # Scaffold a new tool in tools/
ez create skill <name>          # Scaffold a new skill in skills/
```

## Creating a Tool
Tools are [FastMCP](https://github.com/jlowin/fastmcp) servers. Create `tools/<name>/main.py`:
```python
from fastmcp import FastMCP

mcp = FastMCP("my_tool")

@mcp.tool()
def my_function(param: str) -> str:
    \\"\\"\\"Describe what this function does.\\"\\"\\"
    return f"result: {param}"

if __name__ == "__main__":
    mcp.run()
```

Add Python dependencies in `tools/<name>/requirements.txt` (one per line).
ezagent uses `uv` to run each tool in an isolated environment automatically.

Then wire the tool into `agents.yml`:
```yaml
agents:
  my_agent:
    tools: my_tool   # comma-separated list of tool names
```

## Creating a Skill
Skills are markdown files loaded on demand by the agent. Create `skills/<name>.md`:
```markdown
You are an expert at X.
When asked to do Y, follow these steps:
1. Step one
2. Step two
```
The first non-empty line becomes the one-line summary shown in the system prompt.
The full content is loaded only when the agent calls `use_skill("<name>")`.

## agents.yml Reference
```yaml
provider: anthropic          # "anthropic" | "google"  (global default)
model: claude-sonnet-4-20250514  # optional — overrides provider default

agents:
  <name>:
    tools: tool1, other_agent, memory   # CSV: local tools, other agent names, prebuilt names
    skills: skill1, skill2              # CSV: markdown files in skills/ (omit .md)
    description: "What this agent does" # Becomes the system prompt prefix
    provider: anthropic                 # optional per-agent provider override
    model: "..."                        # optional per-agent model override
    schedule:                           # optional cron triggers
      - cron: "0 9 * * *"
        message: "Generate daily report"

discussions:
  <name>:
    participants:
      - agent: agent1
        role: "Proponent"
      - agent: agent2
        role: "Skeptic"
    max_rounds: 5
    termination: rounds    # "rounds" | "consensus"
    moderator: agent3      # optional
    on_deadlock:
      - moderator_decides  # "moderator_decides" | "human_approval" | "record_and_move_on"
```

## Prebuilt Tools (no files needed — just add the name to tools in agents.yml)
| Name                  | What it does                                         | Env var required       |
|-----------------------|------------------------------------------------------|------------------------|
| `memory`              | Persistent semantic memory (store/search/list)       | —                      |
| `web_search`         | Web search + read page content (Brave or Perplexity) | BRAVE_SEARCH_API_KEY or PERPLEXITY_API_KEY |
| `perplexity_research` | Perplexity deep/pro/fast research (Responses API)    | PERPLEXITY_API_KEY     |
| `extract_structured`  | Extract structured data from text (JSON schema)      | PERPLEXITY_API_KEY     |
| `http`                | Generic HTTP client (GET/POST/PUT/PATCH/DELETE)      | —                      |
| `filesystem`          | Read/write/list local files and directories          | —                      |
| `arxiv`               | Search and read ArXiv papers                         | —                      |
| `pdf_reader`          | Extract text from PDF files                          | —                      |

## Agent Delegation
Agents can delegate to other agents by listing them in `tools`. The delegating agent
calls them like any other tool with a `{"message": "..."}` input:
```yaml
agents:
  manager:
    tools: worker          # manager can delegate to worker
    description: "Delegates research tasks"
  worker:
    tools: web_search
    description: "Performs research"
```

## Required Environment Variables
```bash
export ANTHROPIC_API_KEY=sk-ant-...   # for provider: anthropic (default)
export GOOGLE_API_KEY=...             # for provider: google
export BRAVE_SEARCH_API_KEY=...       # web_search with provider=brave (default)
export PERPLEXITY_API_KEY=...        # web_search, perplexity_research, extract_structured
```

## Docker (containerized deployment)

A `Dockerfile` and `docker-compose.yml` are included. Two services share a Unix socket:
- **daemon** — runs `ez start` (the agent daemon)
- **api** — runs `ez serve` (HTTP + WebSocket API on port 7771)

```bash
cp .env.example .env          # fill in your API keys
docker compose up --build     # first run
docker compose up             # subsequent runs
```

Interact via HTTP (no CLI needed from outside the container):
```bash
curl -s -X POST http://localhost:7771/v1/agents/assistant/run \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
```

CLI still works by exec-ing into the daemon container:
```bash
docker compose exec daemon ez status
docker compose exec daemon ez logs
```

Changes to `agents.yml`, `tools/`, and `skills/` are reflected immediately via volume
mount — no rebuild needed. Rebuild only when upgrading ezagent itself.

## Troubleshooting
| Error | Fix |
|-------|-----|
| `No agents.yml found` | Run from the project directory |
| `skill file not found` | Create `skills/<name>.md` |
| `tool ... neither an agent nor a tool directory` | Create `tools/<name>/main.py` |
| `daemon already running` | Run `ez stop` first |
| Stale socket after crash | `rm /tmp/ezagent_*.sock /tmp/ezagent_*.pid` |
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

    # Create CLAUDE.md so Claude Code understands this is an ezagent project
    (base / "CLAUDE.md").write_text(PROJECT_CLAUDE_MD)

    # Create Docker scaffolding for containerized deployment
    (base / "Dockerfile").write_text(DOCKERFILE)
    (base / "docker-compose.yml").write_text(DOCKER_COMPOSE)
    (base / ".dockerignore").write_text(DOCKERIGNORE)
    (base / ".env.example").write_text(ENV_EXAMPLE)

    return base
