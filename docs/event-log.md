## Overview

The event log is a SQLite database under `.ezagent/events.db` in your project. It records agent runs, tool invocations, LLM calls, discussions, and orchestrations so you can debug flows and build analytics.

## How it works

- The daemon creates the DB and tables on startup.
- Rows are inserted when runs start; completion updates are written asynchronously so they do not block the agent loop.
- Paths can be overridden via config (`events_db_path`); the default is `.ezagent/events.db`.

## How to use

### CLI

```bash
ez logs                          # Last 20 agent runs
ez logs --limit 50
ez logs --agent researcher
ez logs --status error
ez logs --orchestration my_plan  # orchestration_runs table
```

Run from a directory that contains (or is under) `agents.yml`.

### Inspect with SQLite

```bash
sqlite3 .ezagent/events.db "SELECT agent_name, status, duration_ms FROM agent_runs ORDER BY started_at DESC LIMIT 10;"
```

### HTTP API

With `ez serve`, use `GET /v1/logs` (list runs) and `GET /v1/logs/{run_uuid}` (run plus tool invocations and LLM calls). See [http-api.md](http-api.md).

## Tables (high level)

| Table | Purpose |
| ----- | ------- |
| `agent_runs` | One row per agent execution (input, output, status, source, timing) |
| `tool_invocations` | Tool name, arguments, result, linked by `run_uuid` |
| `llm_calls` | Per–LLM-round text, tool calls JSON, stop reason |
| `discussion_runs` / `discussion_turns` | Multi-agent discussions |
| `orchestration_runs` | Plan-and-delegate (and similar) orchestrations |

## Gotchas

- If no runs have happened yet, the DB file may not exist and `ez logs` will say there is no event log.
- Finished timestamps on some paths are updated in the background; very tight polling right after a run might still show “running” briefly.
