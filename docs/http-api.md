## Overview

`ez serve` starts a FastAPI app (default `http://127.0.0.1:7771`) that proxies to the daemon over the Unix socket and reads the event-log SQLite DB. Install extras: `uv sync --extra serve`.

## How it works

- **Agent run / discuss / orchestrate** endpoints forward JSON to the daemon; if the daemon is down you get **503** with a hint to run `ez start`.
- **Logs** and **config** endpoints read/write the project directory directly (logs do not require the daemon).
- CORS is open (`*`) for local integration.

## Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| GET | `/v1/status` | Daemon and project status |
| POST | `/v1/daemon/start` | Start daemon (`ez start --daemon`) |
| POST | `/v1/daemon/stop` | Stop daemon, remove socket/PID |
| GET | `/v1/agents` | List agents (summary) |
| GET | `/v1/agents/{name}` | One agent including schedule |
| POST | `/v1/agents/{name}/run` | Body: `{"message": "...", "debug": false}` → `{"text", "debug_events"}` |
| WS | `/v1/agents/{name}/stream` | First message JSON `message`, optional `debug`; then streamed JSON lines |
| POST | `/v1/discussions/{name}/run` | Body: `{"topic": "..."}` |
| WS | `/v1/discussions/{name}/stream` | First message `{"topic": "..."}` |
| GET | `/v1/orchestrations` | List orchestrations |
| GET | `/v1/orchestrations/{name}` | One orchestration |
| POST | `/v1/orchestrations/{name}/run` | Body: `{"message": "..."}` |
| GET | `/v1/logs` | Query: `agent`, `status`, `limit`, `offset` |
| GET | `/v1/logs/{run_uuid}` | Run + tool invocations + LLM calls |
| GET | `/v1/config` | `raw` YAML + `parsed` object |
| PUT | `/v1/config` | Body: `{"content": "<full agents.yml>"}` — validated before write |
| GET | `/v1/tools` | Prebuilt + local tool names |
| POST | `/v1/tools` | Body: `{"name": "..."}` — scaffold tool |
| POST | `/v1/skills` | Body: `{"name": "..."}` — scaffold skill |

## How to use

```bash
uv sync --extra serve
uv run ez serve --port 7771
```

Example:

```bash
curl -s -X POST http://127.0.0.1:7771/v1/agents/assistant/run \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello"}'
```

## Gotchas

- Run and orchestration routes need the **daemon**; starting the API alone is not enough for those.
- `PUT /v1/config` replaces the entire `agents.yml`; invalid YAML or missing `agents` returns **422**.
