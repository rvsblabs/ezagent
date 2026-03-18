# AGENTS.md

### Overview

ezagent is a Python CLI SDK for multi-agent AI systems. The single service is a Python package installed via `uv sync`. See `README.md` for command reference and source layout.

### Documentation map

| Doc | Purpose |
|-----|---------|
| **AGENTS.md** (this file) | Commands, deps, testing, integration tests, daemon/API caveats. |
| **CLAUDE.md** | Long-form developer guide (internals, `agents.yml`, prebuilt tools, circular-loop pitfalls). |
| **README.md** | User-facing CLI and layout. |
| **`.worktree/updating-docs-for-worktree/creating-worktrees.md`** | Git worktrees: create/list/remove a checkout under `.worktree/<name>`, daemon/socket notes. |
| **`tests/ci_integration_env_contract.py`** | Names of env vars the CI integration step must set (contract test + workflow must match). |

When workflow or conventions change, update **AGENTS.md** and/or **CLAUDE.md** so agents stay aligned.

### Running commands

All commands must use `uv run` from the repo root (e.g. `uv run ez --version`). The `ez` CLI entry point is defined in `pyproject.toml`.

### Dependencies

- `uv sync --group dev --extra serve` installs dev deps (pytest) and the HTTP API server extras.
- No linter is configured in the project (no ruff, flake8, mypy, etc.).

### Testing

- **GitHub Actions:** `.github/workflows/ci.yml` runs unit tests (`pytest tests/ -m "not integration"`) and integration tests on pull requests and pushes to `main` (Python 3.10 and 3.12). In the repo **Settings → Branches → Branch protection** for `main`, enable **Require status checks to pass before merging** and select the CI jobs so merges are blocked until tests pass.
- pytest with `asyncio_mode = "auto"` (via pytest-asyncio). Run: `uv run pytest tests/ -v`
- **Local tip:** if you exported `EZAGENT_TEST_*` for manual integration runs, unset them before unit tests or those vars leak into `DiscussionRuntime` / orchestration tests.
- Tests go in `tests/` directory at the repo root.
- **Integration tests** (`subprocess`, real daemon, HTTP via `TestClient`): `uv sync --group dev --extra serve` then `uv run pytest tests/integration -m integration -v`. Marked with `@pytest.mark.integration` for CI (e.g. run on PR before merge). Covers `POST /v1/agents/{name}/run`, `POST /v1/orchestrations/{name}/run`, `POST /v1/discussions/{name}/run`, and `ez orchestrate` against a live daemon.
- **CI-only env (do not set in production):** `EZAGENT_TEST_PLANNER_RESPONSE` (JSON task array string), `EZAGENT_TEST_ORCHESTRATION_FINAL` (final orchestration text after workers), `EZAGENT_TEST_DISCUSSION_DECISION` (immediate discussion decision). Runtime reads these from the **daemon** environment; many fixtures set them when spawning `ez start`, but that is not a substitute for setting them on the **CI job**: any subprocess that does `os.environ.copy()` without adding these can otherwise call real LLMs.
- **CI integration environment:** The step that runs `pytest tests/integration -m integration` must export **`ANTHROPIC_API_KEY`** (any non-empty placeholder is enough for startup checks) **and** the three `EZAGENT_TEST_*` vars above. Canonical YAML: `.github/workflows/ci.yml`. Required key set: `tests/ci_integration_env_contract.py` (unit test `test_github_ci_integration_step_sets_contract_env_vars` fails if the workflow drifts).
- **GitHub Actions:** `.github/workflows/ci.yml` runs unit tests (including the workflow contract test) and integration tests on PRs and pushes to `main` (Python 3.10 and 3.12). Branch protection: require those checks before merge.

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
