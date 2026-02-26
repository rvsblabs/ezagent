# AGENTS.md

## Cursor Cloud specific instructions

### Overview

ezagent is a Python CLI SDK for multi-agent AI systems. The single service is a Python package installed via `uv sync`. See `CLAUDE.md` for full command reference and source layout.

### Running commands

All commands must use `uv run` from the repo root (e.g. `uv run ez --version`). The `ez` CLI entry point is defined in `pyproject.toml`.

### Dependencies

- `uv sync --group dev --extra serve` installs dev deps (pytest) and the HTTP API server extras.
- No linter is configured in the project (no ruff, flake8, mypy, etc.).

### Testing

- pytest with `asyncio_mode = "auto"` (via pytest-asyncio). Run: `uv run pytest tests/ -v`
- Tests go in `tests/` directory at the repo root.

### Daemon startup caveat

- `ez start` requires `ANTHROPIC_API_KEY` (or `GOOGLE_API_KEY` if using `provider: google`, or `DEEPSEEK_API_KEY` if using `provider: deepseek`) to be set. The daemon validates LLM provider credentials at startup and will fail immediately without them.
- CLI commands that do not require a running daemon (`ez init`, `ez status`, `ez tools`, `ez create`, `ez logs`, `ez serve`) work without API keys.
- `ez serve` runs the HTTP API independently of the daemon; it can report config/status/logs even when the daemon is stopped.

### Scaffolding test projects

Use `ez init <name>` from any directory to scaffold a test project. The scaffolded project includes `agents.yml`, `tools/`, `skills/`, and Docker files.
