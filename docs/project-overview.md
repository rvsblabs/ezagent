### Overview

ezagent is a Python CLI SDK for multi-agent AI systems. You define agents, tools, skills, and orchestrations in config; ezagent handles runtime, scheduling, and logging.

### Core concepts

- **Agents**: LLM-powered workers that receive messages, call tools, and return results.
- **Tools**: External capabilities (FastMCP servers) such as HTTP, filesystem, memory, or project-specific tools.
- **Skills**: Markdown prompt snippets that extend an agent’s behavior without code changes.
- **Orchestrations**: Higher-level flows (e.g. plan-and-delegate) that coordinate multiple agents.
- **Daemon & CLI**: A background process plus the `ez` CLI for running agents, jobs, logs, and schedules.
- **HTTP API**: Optional FastAPI server (`ez serve`) exposing agents, orchestrations, and logs via REST and WebSocket.

### Read next

- [AGENTS.md](../AGENTS.md) (repo root — developer map)
- [architecture-overview.md](architecture-overview.md)
- [running-locally.md](running-locally.md)
- [event-log.md](event-log.md) — SQLite event store and `ez logs`
- [http-api.md](http-api.md) — `ez serve` REST and WebSocket
- [tool-pipeline-agents.md](tool-pipeline-agents.md) — `provider: none` tool pipelines
- [writing-docs.md](writing-docs.md)
