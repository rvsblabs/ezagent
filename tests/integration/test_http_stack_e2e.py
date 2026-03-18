"""HTTP + daemon: agent run, orchestration, discussion; CLI orchestrate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ezagent.config import load_config
from ezagent.server import create_app

from tests.integration.conftest import REPO_ROOT, ez_subprocess, wait_for_socket


pytestmark = pytest.mark.integration

_AGENTS_YML = """
provider: anthropic
model: claude-sonnet-4-20250514

orchestrations:
  e2e_orch:
    pattern: plan_and_delegate
    planner: planner_agent
    workers: [orch_worker]
    aggregator: orch_worker
    parallel: true

discussions:
  e2e_disc:
    participants:
      - agent: disc_a
        role: "A"
      - agent: disc_b
        role: "B"
    max_rounds: 2
    termination: rounds

agents:
  planner_agent:
    description: "Planner (not used when test env stubs planner)"
  orch_worker:
    provider: none
    tools: sqlite
    description: "Worker for orchestration e2e"
    pre_tools:
      - tool: sqlite__sqlite_store
        args:
          key: "orch_e2e"
          value: "worker_touched_db"
        as: s
    run_tools:
      - tool: sqlite__sqlite_get
        args:
          key: "orch_e2e"
  disc_a:
    description: "Discussion participant"
  disc_b:
    description: "Discussion participant"
  http_pipe:
    provider: none
    tools: sqlite
    description: "HTTP agent run e2e"
    pre_tools:
      - tool: sqlite__sqlite_store
        args:
          key: "http_e2e"
          value: "http_pipe_ok"
        as: s
    run_tools:
      - tool: sqlite__sqlite_get
        args:
          key: "http_e2e"
"""


@pytest.fixture
def stack_project(tmp_path: Path) -> Path:
    p = tmp_path / "stack"
    p.mkdir()
    (p / "agents.yml").write_text(_AGENTS_YML.strip() + "\n")
    (p / "skills").mkdir()
    (p / "tools").mkdir()
    (p / "pyproject.toml").write_text(
        '[project]\nname = "st"\nversion = "0.1.0"\nrequires-python = ">=3.10"\n'
    )
    return p


@pytest.fixture
def stack_daemon(stack_project: Path):
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = env.get(
        "ANTHROPIC_API_KEY", "sk-ant-api03-integration-test-dummy-key-000000000000"
    )
    env["EZAGENT_TEST_PLANNER_RESPONSE"] = json.dumps(
        [{"agent": "orch_worker", "message": "run sqlite pipeline"}]
    )
    env["EZAGENT_TEST_ORCHESTRATION_FINAL"] = "orch_http_e2e_final"
    env["EZAGENT_TEST_DISCUSSION_DECISION"] = "disc_http_e2e_final"
    proc = subprocess.Popen(
        ["uv", "run", "--project", str(REPO_ROOT), "ez", "start"],
        cwd=str(stack_project),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    cfg = load_config(stack_project)
    sock = Path(cfg.socket_path)
    pid_file = Path(cfg.pid_path)
    try:
        if not wait_for_socket(sock, timeout=60.0):
            proc.terminate()
            proc.wait(timeout=10)
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"stack daemon failed: {err[:2000]}")
        yield stack_project
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        ez_subprocess(stack_project, "stop", timeout=30)
        for path in (sock, pid_file):
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    pass


def test_http_post_agent_run(stack_daemon: Path):
    cfg = load_config(stack_daemon)
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/v1/agents/http_pipe/run",
            json={"message": "go", "debug": False},
        )
    assert r.status_code == 200, r.text
    assert "http_pipe_ok" in r.json().get("text", "")


def test_http_post_orchestration_run(stack_daemon: Path):
    cfg = load_config(stack_daemon)
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/v1/orchestrations/e2e_orch/run",
            json={"message": "plan something"},
        )
    assert r.status_code == 200, r.text
    assert r.json().get("text") == "orch_http_e2e_final"


def test_http_post_discussion_run(stack_daemon: Path):
    cfg = load_config(stack_daemon)
    app = create_app(cfg)
    with TestClient(app) as client:
        r = client.post(
            "/v1/discussions/e2e_disc/run",
            json={"topic": "integration topic"},
        )
    assert r.status_code == 200, r.text
    assert r.json().get("decision") == "disc_http_e2e_final"


def test_cli_ez_orchestrate_e2e(stack_daemon: Path):
    r = ez_subprocess(stack_daemon, "orchestrate", "e2e_orch", "do it", timeout=120)
    assert r.returncode == 0, r.stderr
    assert "orch_http_e2e_final" in r.stdout
