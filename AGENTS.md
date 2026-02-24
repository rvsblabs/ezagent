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
- Tests are organized in `tests/` directory at the repo root.
- Test structure:
  - `test_smoke.py` - Basic import and CLI smoke tests
  - `systematic/` - Organized systematic tests by component:
    - `test_config.py` - Configuration validation
    - `test_daemon.py` - Daemon socket handling and scheduler
    - `test_discussions.py` - Multi-agent discussions
    - `test_event_log.py` - Event logging and persistence
    - `test_llm_providers.py` - LLM provider implementations
    - `test_tools.py` - Tool management and MCP clients

### Daemon startup caveat

- `ez start` requires `ANTHROPIC_API_KEY` (or `GOOGLE_API_KEY` if using `provider: google`) to be set. The daemon validates LLM provider credentials at startup and will fail immediately without them.
- CLI commands that do not require a running daemon (`ez init`, `ez status`, `ez tools`, `ez create`, `ez logs`, `ez serve`) work without API keys.
- `ez serve` runs the HTTP API independently of the daemon; it can report config/status/logs even when the daemon is stopped.

### Scaffolding test projects

Use `ez init <name>` from any directory to scaffold a test project. The scaffolded project includes `agents.yml`, `tools/`, `skills/`, and Docker files.

### Code Quality Notes

Recent systematic code review identified and fixed several issues:

1. **Async Resource Management**: Ensured proper cleanup of asyncio resources (socket writers, MCP clients)
2. **Google Provider Compatibility**: Fixed tool result name mapping for Gemini API compatibility
3. **Event Logging Consistency**: Corrected source parameter tracking for discussion moderator calls
4. **Defensive Error Handling**: Added None checks in cleanup paths to prevent shutdown failures

All fixes have test coverage in `tests/systematic/`.
