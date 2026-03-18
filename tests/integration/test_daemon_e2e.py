"""Daemon lifecycle: start, run tool-only agent via socket, logs, stop."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from ezagent.config import load_config

from tests.integration.conftest import REPO_ROOT, ez_subprocess, wait_for_socket


pytestmark = pytest.mark.integration


@pytest.fixture
def daemon_proc(integration_project: Path, fake_anthropic_key: str):
    env = os.environ.copy()
    env["ANTHROPIC_API_KEY"] = fake_anthropic_key
    proc = subprocess.Popen(
        ["uv", "run", "--project", str(REPO_ROOT), "ez", "start"],
        cwd=str(integration_project),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    cfg = load_config(integration_project)
    sock = Path(cfg.socket_path)
    pid_file = Path(cfg.pid_path)
    try:
        if not wait_for_socket(sock, timeout=60.0):
            proc.terminate()
            proc.wait(timeout=10)
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"Daemon socket never appeared. stderr: {err[:2000]}")
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        ez_subprocess(integration_project, "stop", timeout=30)
        for p in (sock, pid_file):
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass


def test_daemon_run_tool_only_sqlite_pipeline(daemon_proc, integration_project: Path):
    r = ez_subprocess(
        integration_project,
        "run",
        "sqlite_pipe",
        "trigger",
        timeout=120,
    )
    assert r.returncode == 0, f"stderr={r.stderr!r} stdout={r.stdout!r}"
    assert "integration_e2e_value" in r.stdout

    r2 = ez_subprocess(integration_project, "logs", "--agent", "sqlite_pipe", "--limit", "5")
    assert r2.returncode == 0
    assert "sqlite_pipe" in r2.stdout
    assert "success" in r2.stdout.lower() or "SUCCESS" in r2.stdout


def test_ez_status_while_daemon_running(daemon_proc, integration_project: Path):
    r = ez_subprocess(integration_project, "status", timeout=30)
    assert r.returncode == 0
    assert "Daemon: running" in r.stdout
