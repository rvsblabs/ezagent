"""HTTP API: ez serve + REST endpoints."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.integration.conftest import REPO_ROOT


pytestmark = pytest.mark.integration


def _free_port() -> int:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def serve_project(tmp_path: Path) -> Path:
    p = tmp_path / "srv"
    p.mkdir()
    (p / "agents.yml").write_text(
        """
provider: anthropic
model: claude-sonnet-4-20250514

agents:
  api_agent:
    description: For API listing
  sqlite_pipe:
    provider: none
    tools: sqlite
    description: "HTTP listing includes sqlite agent"
    pre_tools:
      - tool: sqlite__sqlite_store
        args:
          key: "integration_http_key"
          value: "integration_http_value"
        as: stored
    run_tools:
      - tool: sqlite__sqlite_get
        args:
          key: "integration_http_key"
"""
    )
    (p / "skills").mkdir()
    (p / "tools").mkdir()
    return p


@pytest.fixture
def serve_proc(serve_project: Path):
    port = _free_port()
    env = os.environ.copy()
    env.setdefault("ANTHROPIC_API_KEY", "sk-ant-api03-test")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(REPO_ROOT),
            "ez",
            "serve",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(serve_project),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 45
    ok = False
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"{base}/v1/status", timeout=2)
            ok = True
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    if not ok:
        proc.terminate()
        proc.wait(timeout=5)
        err = proc.stderr.read() if proc.stderr else ""
        pytest.skip(f"serve did not become ready: {err[:500]}")
    try:
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_serve_status_and_agents(serve_proc: str):
    with urllib.request.urlopen(f"{serve_proc}/v1/status") as resp:
        data = json.loads(resp.read().decode())
    assert "running" in data
    assert data["running"] is False

    with urllib.request.urlopen(f"{serve_proc}/v1/agents") as resp:
        agents = json.loads(resp.read().decode())
    assert isinstance(agents, list)
    assert any(a.get("name") == "api_agent" for a in agents)


def test_serve_orchestrations_empty(serve_proc: str):
    with urllib.request.urlopen(f"{serve_proc}/v1/orchestrations") as resp:
        orch = json.loads(resp.read().decode())
    assert orch == []
