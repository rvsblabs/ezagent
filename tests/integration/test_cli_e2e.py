"""CLI workflows without a long-lived daemon."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from tests.integration.conftest import REPO_ROOT, ez_subprocess


pytestmark = pytest.mark.integration


def test_ez_version():
    r = subprocess.run(
        ["uv", "run", "--project", str(REPO_ROOT), "ez", "--version"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0
    assert "0.1.0" in r.stdout


def test_ez_init_create_tool_skill_logs(tmp_path: Path):
    r = ez_subprocess(tmp_path, "init", "myapp", timeout=90)
    assert r.returncode == 0, r.stderr
    app = tmp_path / "myapp"
    assert (app / "agents.yml").is_file()
    assert (app / "tools").is_dir()

    r2 = ez_subprocess(app, "create", "tool", "alpha", timeout=60)
    assert r2.returncode == 0, r2.stderr
    assert (app / "tools" / "alpha" / "main.py").is_file()

    r3 = ez_subprocess(app, "create", "skill", "beta", timeout=60)
    assert r3.returncode == 0, r3.stderr
    assert (app / "skills" / "beta.md").is_file()

    r4 = ez_subprocess(app, "update-docs", timeout=60)
    assert r4.returncode == 0, r4.stderr

    r5 = ez_subprocess(app, "logs", "--limit", "5", timeout=30)
    assert r5.returncode == 0
    assert "No event log" in r5.stdout or "No logs" in r5.stdout

    r6 = ez_subprocess(app, "status", timeout=30)
    assert r6.returncode == 0
    assert "Daemon: not running" in r6.stdout


def test_ez_tools_lists_prebuilt(tmp_path: Path):
    r = ez_subprocess(tmp_path, "tools", timeout=30)
    assert r.returncode == 0
    assert "sqlite" in r.stdout
    assert "memory" in r.stdout


def test_ez_run_mock_fixture(tmp_path: Path):
    skills = tmp_path / "skills"
    skills.mkdir()
    (skills / "s.md").write_text("# S\nHelpful.")
    (tmp_path / "agents.yml").write_text(
        """
agents:
  assistant:
    description: Test
    skills: s
"""
    )
    fix = {
        "agent": "assistant",
        "input": "hi",
        "llm_calls": [{"text": "mocked reply", "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    fx = tmp_path / "f.yml"
    fx.write_text(yaml.dump(fix))
    r = ez_subprocess(
        tmp_path,
        "run",
        "assistant",
        "hi",
        "--mock",
        str(fx),
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    assert "mocked reply" in r.stdout


def test_ez_eval_with_fixtures(tmp_path: Path):
    (tmp_path / "agents.yml").write_text(
        """
agents:
  assistant:
    description: T
"""
    )
    fix = {
        "agent": "assistant",
        "input": "q",
        "llm_calls": [{"text": "eval-out-xyz", "tool_calls": [], "stop_reason": "end_turn"}],
        "tool_calls": {},
    }
    (tmp_path / "case.yml").write_text(yaml.dump(fix))
    eval_yml = tmp_path / "eval.yaml"
    eval_yml.write_text(
        """
agent: assistant
cases:
  - id: c1
    input: "q"
    expected: "eval-out-xyz"
    fixture: case.yml
"""
    )
    r = ez_subprocess(tmp_path, "eval", str(eval_yml), timeout=90)
    assert r.returncode == 0, r.stderr
    assert "1/1 passed" in r.stdout
