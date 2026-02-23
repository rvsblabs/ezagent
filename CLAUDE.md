# ezagent — Developer Guide for Claude Code

## What is ezagent?
Low-code CLI SDK for creating multi-agent AI systems using LLMs (Anthropic Claude, Google Gemini) and FastMCP tools. Users define agents, tools, and skills in `agents.yml` — ezagent handles all runtime wiring.

## Key Commands (always use `uv run` in this repo)
```bash
uv sync                              # Install dependencies
uv run ez --version                  # Verify install
uv run ez init testproject           # Scaffold a test project
cd testproject && uv run ez start    # Start daemon (foreground)
uv run ez assistant "hello"          # Message an agent
uv run ez --debug assistant "hello"  # Debug mode (prints tool calls to stderr)
uv run ez stop                       # Stop daemon
uv run ez status                     # Show agents, schedules, next run times
ez create tool <name>                # Scaffold a new tool in tools/
ez create skill <name>               # Scaffold a new skill in skills/
```

> **In user projects** (not this repo): run `ez update-docs` after upgrading ezagent to regenerate the project's `CLAUDE.md` from the latest template.

## Source Layout
```
ezagent/
  cli.py          # Click CLI — init, start, stop, status, run, discuss, tools, create
  config.py       # Pydantic models: ProjectConfig, AgentConfig, DiscussionConfig, ScheduleEntry
  agent.py        # Agent class — agentic tool-use loop (initialize / run / shutdown)
  daemon.py       # AgentDaemon — Unix socket server + cron scheduler
  scaffold.py     # create_project(), create_tool(), create_skill() + template strings
  discussion.py   # DiscussionRuntime — multi-agent turn-based discussions
  external.py     # Git-based external tools/skills resolution
  llm/
    base.py       # Abstract LLMProvider + LLMResponse/ToolCall dataclasses
    anthropic.py  # AnthropicProvider (claude-sonnet-4-20250514 default)
    google.py     # GoogleProvider (gemini-2.0-flash default)
    __init__.py   # create_provider(name, model) factory
  tools/
    manager.py    # ToolManager — FastMCP client lifecycle, schema conversion, tool dispatch
    builtins/
      __init__.py # PREBUILT_TOOLS dict: name → Path to builtin package dir
      memory/     # Persistent vector memory (Milvus Lite + sentence-transformers)
      web_search/ # Brave Search API + page reading
      http/       # Generic HTTP client
      filesystem/ # Read/write/list local files
      arxiv/      # ArXiv paper search
      pdf_reader/ # PDF text extraction
```

## Core Abstractions

### Agent (`agent.py`)
- `Agent.initialize()` — loads skills into system prompt, connects ToolManager to MCP servers
- `Agent.run(message, depth, debug) -> AgentResult` — agentic loop: LLM → tool calls → results → repeat until no tool calls remain
- Skills are loaded lazily via the synthetic `use_skill` tool (keeps context lean)
- Agent-as-tool: tool name is `agent_<name>` with input schema `{"message": str}`
- Discussion-as-tool: tool name matches the discussion name, input schema `{"topic": str}`
- Max recursion depth: 10

### ToolManager (`tools/manager.py`)
- Connects to each tool via FastMCP STDIO transport:
  - Local project tools (no requirements): `PythonStdioTransport`
  - Tools with `requirements.txt` or `pyproject.toml`: `UvStdioTransport` (isolated uv env)
- `get_tool_schemas()` → list of Anthropic-format tool dicts
- `call_tool(name, arguments)` → dispatches to the correct MCP client

### LLMProvider (`llm/base.py`)
```python
class LLMProvider(ABC):
    async def chat(messages, system="", tools=None) -> LLMResponse
```
`LLMResponse` has `.text` (str) and `.tool_calls` (list of `ToolCall(id, name, input)`).

### Config (`config.py`)
- `load_config()` — walks up from cwd to find `agents.yml`, validates everything
- Tools validated: must be a prebuilt name, agent name, discussion name, local `tools/<name>/main.py`, or git ref
- Skills validated: must exist as `skills/<name>.md`
- Circular agent references detected via DFS at load time

## How to Add New Things

### New prebuilt tool
1. Create `ezagent/tools/builtins/<name>/` with `main.py` (FastMCP server) and `requirements.txt`
2. Add entry to `PREBUILT_TOOLS` dict in `ezagent/tools/builtins/__init__.py`
3. Document in `README.md` under the prebuilt tools table

### New CLI command
- Add `@cli.command()` in `cli.py` (uses Click)
- Commands that talk to a running agent: connect via Unix socket like `ez run` does

### New LLM provider
1. Create `ezagent/llm/<name>.py`, subclass `LLMProvider`, implement `async chat()`
2. Register in `create_provider()` factory in `ezagent/llm/__init__.py`

### New scaffold template
- Add template strings and logic in `scaffold.py`
- `create_project()` is called by `ez init`
- `create_tool()` / `create_skill()` called by `ez create tool/skill`

## agents.yml Full Reference
```yaml
provider: anthropic          # "anthropic" | "google" (global default)
model: claude-sonnet-4-20250514  # optional global model

agents:
  <name>:
    tools: tool1, agent2     # CSV: local tool dirs, other agent names, prebuilt names, or git refs
    skills: skill1           # CSV: markdown files in skills/ (omit .md)
    description: "..."       # Becomes system prompt prefix
    provider: anthropic      # optional per-agent override
    model: "..."             # optional per-agent model override
    schedule:
      - cron: "0 9 * * *"   # standard 5-field cron expression
        message: "..."       # message sent to agent on schedule

discussions:
  <name>:
    participants:
      - agent: <agent_name>
        role: "..."
    max_rounds: 5
    termination: rounds      # "rounds" | "consensus"
    moderator: <agent_name>  # optional
    on_deadlock:             # "moderator_decides" | "human_approval" | "record_and_move_on"
      - moderator_decides
    max_tokens: 50000
    max_duration: 300        # seconds
```

## Prebuilt Tools Reference
| Name | Functions | Env var required |
|------|-----------|-----------------|
| `memory` | memory_store, memory_search, memory_delete, memory_list, memory_collections | — |
| `web_search` | web_search, web_search_read | BRAVE_SEARCH_API_KEY |
| `http` | http_request, http_read | — |
| `filesystem` | read_file, write_file, list_directory, create_directory | — |
| `arxiv` | arxiv paper search and read | — |
| `pdf_reader` | pdf_read (extract text) | — |

## Daemon Internals
- Socket: `/tmp/ezagent_<md5-of-project-dir>.sock`
- PID file: `/tmp/ezagent_<md5-of-project-dir>.pid`
- Scheduler log: `.ezagent/scheduler.log` in project dir
- Memory DB: `.ezagent/memory/milvus.db` in project dir

## Common Errors
| Error | Fix |
|-------|-----|
| `No agents.yml found` | Run from project dir or a parent |
| `skill file not found` | Create `skills/<name>.md` |
| `tool ... neither an agent nor a tool directory` | Create `tools/<name>/main.py` |
| `daemon already running` | `uv run ez stop` first |
| Stale socket after crash | `rm /tmp/ezagent_*.sock /tmp/ezagent_*.pid` |
| `ANTHROPIC_API_KEY not set` | `export ANTHROPIC_API_KEY=sk-ant-...` |
