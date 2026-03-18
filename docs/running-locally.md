## Running locally

ezagent is a Python CLI run via `uv` from this repo.

### Prerequisites

- **Python + uv**: Python 3.11+ and `uv` installed.
- **LLM API key**: One of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, or `DEEPSEEK_API_KEY` set in your shell.

### Setup

1. **Install deps**: `uv sync`
2. **Dev deps (tests)**: `uv sync --group dev`
3. **HTTP server extras (`ez serve`)**: `uv sync --extra serve`

### Common commands

- **Version**: `uv run ez --version`
- **Start daemon**: `uv run ez start`
- **Talk to agent**: `uv run ez assistant "hello"`
- **Status**: `uv run ez status`
- **Logs**: `uv run ez logs`
- **Stop daemon**: `uv run ez stop`
- **Unit tests**: `uv sync --group dev` then `uv run pytest tests/`
- **Integration tests** (daemon + HTTP API paths): `uv sync --group dev --extra serve` then `uv run pytest tests/integration -m integration -v`

**CI / automation:** the integration test step must also export those three vars plus `ANTHROPIC_API_KEY` on the runner (not only inside fixtures). See **AGENTS.md** and `tests/ci_integration_env_contract.py`. Never use test env vars in production.

### If something breaks

- **Missing API key**: Set the key for your `provider`, then `uv run ez stop` and `uv run ez start`.
- **Stale daemon/socket**: `uv run ez stop`, then remove `/tmp/ezagent_*.sock` and `/tmp/ezagent_*.pid` if they exist.
- **Dependency issues**: Re-run `uv sync` (and `uv sync --group dev --extra serve` if using tests/HTTP).
- **Test failures**: `uv run pytest tests/ -x -q` and fix the first failing test.
