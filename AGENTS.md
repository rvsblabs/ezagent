# AGENTS.md

### Overview

ezagent is a Python CLI SDK for multi-agent AI systems. The single service is a Python package installed via `uv sync`. See `README.md` for command reference and source layout.

### Running commands

All commands must use `uv run` from the repo root (e.g. `uv run ez --version`). The `ez` CLI entry point is defined in `pyproject.toml`.

### Dependencies

- `uv sync --group dev --extra serve` installs dev deps (pytest) and the HTTP API server extras.
- No linter is configured in the project (no ruff, flake8, mypy, etc.).

### Testing

- pytest with `asyncio_mode = "auto"` (via pytest-asyncio). Run: `uv run pytest tests/ -v`
- Tests go in `tests/` directory at the repo root.
- **Integration tests** (`subprocess`, real daemon, HTTP via `TestClient`): `uv sync --group dev --extra serve` then `uv run pytest tests/integration -m integration -v`. Marked with `@pytest.mark.integration` for CI (e.g. run on PR before merge). Covers `POST /v1/agents/{name}/run`, `POST /v1/orchestrations/{name}/run`, `POST /v1/discussions/{name}/run`, and `ez orchestrate` against a live daemon.
- **CI-only env (do not set in production):** `EZAGENT_TEST_PLANNER_RESPONSE` (JSON task array string), `EZAGENT_TEST_ORCHESTRATION_FINAL` (final orchestration text after workers), `EZAGENT_TEST_DISCUSSION_DECISION` (immediate discussion decision). Integration tests set these on the daemon process so orchestration/discussion paths run without calling live LLMs.

### Daemon startup caveat

- `ez start` requires `ANTHROPIC_API_KEY` (or `OPENAI_API_KEY` for `provider: openai`, `GOOGLE_API_KEY` for `provider: google`, or `DEEPSEEK_API_KEY` for `provider: deepseek`) to be set. The daemon validates LLM provider credentials at startup and will fail immediately without them.
- CLI commands that do not require a running daemon (`ez init`, `ez status`, `ez tools`, `ez create`, `ez logs`, `ez serve`) work without API keys.
- `ez serve` runs the HTTP API independently of the daemon; it can report config/status/logs even when the daemon is stopped.

### Scaffolding test projects

Use `ez init <name>` from any directory to scaffold a test project. The scaffolded project includes `agents.yml`, `tools/`, `skills/`, and Docker files.

### Tool-only agents and scheduled tool pipelines

- Agents with `provider: none` run **deterministic tool pipelines** without any LLM calls.
- Configure `pre_tools` and `run_tools` on an agent to run tools in order and share intermediate results.
- Scheduled tool pipelines work by adding a `schedule` entry to a `provider: none` agent; the daemon executes the configured tools directly on each cron tick.
