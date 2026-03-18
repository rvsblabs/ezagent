## What this covers

A fast, high‑level mental model for ezagent’s structure and a single CLI request flow.

### Main pieces

- **CLI (`ez`)**: Entry point for all commands (init, run agents, daemon control, logs, HTTP server).
- **Daemon**: Long‑running scheduler/router that runs agents on demand or on cron.
- **Agents**: Config‑driven LLM loops that call tools, other agents, discussions, and orchestrations.
- **Tools (FastMCP)**: External capabilities (filesystem, web search, sqlite, HTTP, custom tools) exposed to agents.
- **LLM providers**: Pluggable chat backends (Anthropic, Google, DeepSeek, OpenAI) used by agents.
- **Event log**: SQLite database of runs, tool calls, discussions, and orchestrations for debugging and analytics.
- **HTTP server**: FastAPI service exposing agents, status, and logs over REST/WebSocket.

### How a request flows (`uv run ez assistant "hello"`)

1. **CLI loads config**: `ez` finds `agents.yml`, loads the `assistant` agent, and locates the daemon/socket.
2. **CLI sends request**: It sends a "run agent" message with `"hello"` over the Unix socket.
3. **Agent loop starts**: The daemon runs `Agent`, which calls the configured LLM provider with tools attached.
4. **LLM plans + uses tools**: The LLM returns text and tool calls; the runtime invokes tools via `ToolManager` and feeds results back.
5. **Agent finishes answer**: When the LLM stops calling tools, the final text response is produced.
6. **CLI prints output**: The daemon streams the response (and logs events) back to the CLI, which prints it.

### Key files

- **`ezagent/cli.py`**: `ez` command and argument parsing.
- **`ezagent/daemon.py`**: Daemon, scheduler, and socket server.
- **`ezagent/agent.py`**: Core agent loop (LLM + tools + recursion limits).
- **`ezagent/tools/manager.py`**: FastMCP tool lifecycle and dispatch.
- **`ezagent/llm/__init__.py`**: Provider factory (Anthropic/Google/DeepSeek/OpenAI).
- **`ezagent/event_log.py`**: Structured logging to the SQLite event DB.

