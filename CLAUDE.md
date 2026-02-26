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
uv run ez logs                       # Show recent agent run logs
uv run ez logs --agent <name>        # Filter logs by agent name
uv run ez logs --status error        # Filter logs by status (running|success|error)
uv run ez logs --orchestration <n>  # Filter logs by orchestration name
uv run ez logs --limit 50            # Change number of rows shown (default 20)
uv run ez orchestrate <name> "msg"   # Run plan-and-delegate orchestration
ez create tool <name>                # Scaffold a new tool in tools/
ez create skill <name>               # Scaffold a new skill in skills/
uv sync --extra serve                # Install HTTP server deps (fastapi + uvicorn)
uv run ez serve                      # Start REST + WebSocket API on http://127.0.0.1:7771
uv run ez serve --port 8080          # Custom port
```

## Testing
```bash
uv sync --group dev                  # Install dev dependencies (pytest)
uv run pytest tests/                 # Run all tests
uv run pytest tests/ -x -q          # Fail-fast, quiet output
uv run pytest tests/test_event_log.py       # EventLogger unit tests (agent_runs, tool_invocations, llm_calls, discussion_runs, discussion_turns)
uv run pytest tests/test_orchestration_event_log.py  # Orchestration + EventLogger
uv run pytest tests/test_config_and_cli.py  # Config + CLI logs command
uv run pytest tests/test_llm_providers.py   # LLM provider factory + DeepSeek + OpenAI + Google
```

> **In user projects** (not this repo): run `ez update-docs` after upgrading ezagent to regenerate the project's `CLAUDE.md` from the latest template.

## Source Layout
```
ezagent/
  cli.py          # Click CLI — init, start, stop, status, run, discuss, logs, tools, create, serve
  server.py       # FastAPI app — REST + WebSocket bridge to daemon + SQLite (ez serve)
  config.py       # Pydantic models: ProjectConfig, AgentConfig, DiscussionConfig, OrchestrationConfig
  orchestration.py # PlanAndDelegateRuntime — plan-and-delegate orchestration
  agent.py        # Agent class — agentic tool-use loop (initialize / run / shutdown)
  daemon.py       # AgentDaemon — Unix socket server + cron scheduler
  scaffold.py     # create_project(), create_tool(), create_skill() + template strings
  discussion.py   # DiscussionRuntime — multi-agent turn-based discussions
  event_log.py    # EventLogger — SQLite event store (agent runs, tool calls, LLM calls, discussions)
  external.py     # Git-based external tools/skills resolution
  llm/
    base.py       # Abstract LLMProvider + LLMResponse/ToolCall dataclasses
    anthropic.py  # AnthropicProvider (claude-sonnet-4-20250514 default)
    google.py     # GoogleProvider (gemini-2.0-flash default)
    deepseek.py   # DeepSeekProvider (deepseek-chat default)
    openai.py     # OpenAIProvider (gpt-4o default)
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
tests/
  test_event_log.py              # EventLogger unit tests (agent_runs, tool_invocations, llm_calls, discussion_runs, discussion_turns)
  test_orchestration_event_log.py # Orchestration runs + EventLogger
  test_config_and_cli.py         # ProjectConfig.events_db_path + ez logs CLI
  test_llm_providers.py          # create_provider + DeepSeek, OpenAI, Google (mock-based)
```

## Core Abstractions

### Agent (`agent.py`)
- `Agent.initialize()` — loads skills into system prompt, connects ToolManager to MCP servers
- `Agent.run(message, depth, debug, source, parent_run_uuid) -> AgentResult` — agentic loop: LLM → tool calls → results → repeat until no tool calls remain
- `source` values: `"manual"` (CLI/direct), `"scheduled"` (cron), `"delegation"` (agent-as-tool), `"discussion"` (inside a discussion turn)
- Skills are loaded lazily via the synthetic `use_skill` tool (keeps context lean)
- Agent-as-tool: tool name is `agent_<name>` with input schema `{"message": str}`
- Discussion-as-tool: tool name matches the discussion name, input schema `{"topic": str}`
- Orchestration-as-tool: tool name matches orchestration name, input schema `{"message": str}`
- Max recursion depth: 10

### EventLogger (`event_log.py`)
- `EventLogger.setup(db_path)` — creates schema, called once at daemon startup
- `start_*` methods await the INSERT (so the row exists before `finish_*` updates it)
- `finish_*` methods are fire-and-forget (`asyncio.create_task`) — never block the agent loop
- All writes use a single-threaded `ThreadPoolExecutor` so SQLite access is serialized
- DB location: `.ezagent/events.db` in the project directory (`config.events_db_path`)

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
- Tools validated: must be a prebuilt name, agent name, discussion name, orchestration name, local `tools/<name>/main.py`, or git ref
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
provider: anthropic          # "anthropic" | "google" | "deepseek" | "openai" (global default)
model: claude-sonnet-4-20250514  # optional global model

agents:
  <name>:
    tools: tool1, agent2     # CSV: local tool dirs, other agent names, prebuilt names, or git refs
    skills: skill1           # CSV: markdown files in skills/ (omit .md)
    description: "..."       # Becomes system prompt prefix
    provider: anthropic      # optional per-agent override (anthropic | google | deepseek | openai)
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

orchestrations:
  <name>:
    pattern: plan_and_delegate
    planner: <agent_name>    # Agent that decomposes requests into tasks
    workers: [agent1, agent2] # Agents that run tasks (in parallel)
    aggregator: <agent_name> # Agent that synthesizes results
    parallel: true           # Run workers in parallel (default true)
```

## Prebuilt Tools Reference
| Name | Functions | Env var required |
|------|-----------|-----------------|
| `memory` | memory_store, memory_search, memory_delete, memory_list, memory_collections | — |
| `web_search` | web_search, web_search_read | BRAVE_SEARCH_API_KEY or PERPLEXITY_API_KEY |
| `perplexity_research` | perplexity_research (presets: fast-search, pro-search, deep-research, advanced-deep-research) | PERPLEXITY_API_KEY |
| `extract_structured` | extract_structured (text, json_schema) | PERPLEXITY_API_KEY |
| `http` | http_request, http_read | — |
| `filesystem` | read_file, write_file, list_directory, create_directory | — |
| `arxiv` | arxiv paper search and read | — |
| `pdf_reader` | pdf_read (extract text) | — |

## Daemon Internals
- Socket: `/tmp/ezagent_<md5-of-project-dir>.sock`
- PID file: `/tmp/ezagent_<md5-of-project-dir>.pid`
- Scheduler log: `.ezagent/scheduler.log` in project dir
- Memory DB: `.ezagent/memory/milvus.db` in project dir
- Event log DB: `.ezagent/events.db` in project dir (SQLite, 6 tables)

## Event Log Schema
```
agent_runs         run_uuid, agent_name, input_message, output_text, status, error_message,
                   depth, source, parent_run_uuid, started_at, finished_at, duration_ms
tool_invocations   call_uuid, run_uuid, tool_name, input_json, output_text,
                   status, error_message, started_at, finished_at, duration_ms
llm_calls          call_uuid, run_uuid, call_number, output_text, tool_calls_json,
                   stop_reason, started_at, finished_at, duration_ms
discussion_runs    discussion_uuid, discussion_name, topic, status, terminal_state,
                   decision, dissent, rounds_completed, started_at, finished_at, duration_ms
discussion_turns   discussion_uuid, agent_name, role, content, round_number, created_at
orchestration_runs orchestration_uuid, orchestration_name, message, status, output_text,
                   error_message, started_at, finished_at, duration_ms
```
Inspect directly: `sqlite3 .ezagent/events.db "SELECT agent_name,status,duration_ms FROM agent_runs;"`

## Common Errors
| Error | Fix |
|-------|-----|
| `No agents.yml found` | Run from project dir or a parent |
| `skill file not found` | Create `skills/<name>.md` |
| `tool ... neither an agent nor a tool directory` | Create `tools/<name>/main.py` |
| `daemon already running` | `uv run ez stop` first |
| Stale socket after crash | `rm /tmp/ezagent_*.sock /tmp/ezagent_*.pid` |
| `ANTHROPIC_API_KEY not set` | `export ANTHROPIC_API_KEY=sk-ant-...` |
| `GOOGLE_API_KEY not set` | `export GOOGLE_API_KEY=...` (when using provider: google) |
| `DEEPSEEK_API_KEY not set` | `export DEEPSEEK_API_KEY=...` (when using provider: deepseek) |
| `OPENAI_API_KEY not set` | `export OPENAI_API_KEY=...` (when using provider: openai) |
