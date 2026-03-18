"""Shared helpers for subprocess-based integration tests.

CI: the job that runs this package must set the env vars in
``tests/ci_integration_env_contract`` (see AGENTS.md — CI integration environment).
Fixtures that spawn daemons often set EZAGENT_TEST_* explicitly; job-level env is still required.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

_FAKE_ANTHROPIC = "sk-ant-api03-integration-test-dummy-key-000000000000"


def ez_subprocess(
    project_dir: Path,
    *args: str,
    env: dict[str, str] | None = None,
    timeout: float = 120,
) -> subprocess.CompletedProcess[str]:
    """Run `ez` CLI against project_dir using this worktree's ezagent package."""
    full_env = os.environ.copy()
    full_env.setdefault("ANTHROPIC_API_KEY", _FAKE_ANTHROPIC)
    if env:
        full_env.update(env)
    return subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "ez", *args],
        cwd=str(project_dir),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture
def fake_anthropic_key() -> str:
    return _FAKE_ANTHROPIC


@pytest.fixture
def integration_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir()
    agents = """
provider: anthropic
model: claude-sonnet-4-20250514

agents:
  sqlite_pipe:
    provider: none
    tools: sqlite
    description: "Integration sqlite pipeline"
    pre_tools:
      - tool: sqlite__sqlite_store
        args:
          key: "integration_e2e_key"
          value: "integration_e2e_value"
        as: stored
    run_tools:
      - tool: sqlite__sqlite_get
        args:
          key: "integration_e2e_key"
"""
    (proj / "agents.yml").write_text(agents.strip() + "\n")
    (proj / "skills").mkdir()
    (proj / "tools").mkdir()
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "it"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
    )
    return proj


def wait_for_socket(sock: Path, timeout: float = 45.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sock.exists():
            return True
        time.sleep(0.15)
    return False
