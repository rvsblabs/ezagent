"""Tests for ProjectConfig.events_db_path and ez logs CLI (_read_logs, _read_orchestration_logs)."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from ezagent.cli import cli, _read_logs, _read_orchestration_logs
from ezagent.config import AgentConfig, ProjectConfig


# --------------------------------------------------------------------------- #
# ProjectConfig.events_db_path
# --------------------------------------------------------------------------- #


def test_events_db_path():
    """ProjectConfig.events_db_path returns project_dir/.ezagent/events.db."""
    project_dir = Path("/tmp/myproject")
    config = ProjectConfig(
        agents={"assistant": AgentConfig(description="Test")},
        project_dir=project_dir,
    )
    assert config.events_db_path == project_dir / ".ezagent" / "events.db"


# --------------------------------------------------------------------------- #
# _read_logs and _read_orchestration_logs (used by ez logs)
# --------------------------------------------------------------------------- #


@pytest.fixture
def events_db():
    """Temp events.db with agent_runs and orchestration_runs data."""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE agent_runs (
            run_uuid TEXT PRIMARY KEY, agent_name TEXT, input_message TEXT,
            output_text TEXT, status TEXT, error_message TEXT, depth INTEGER,
            source TEXT, parent_run_uuid TEXT, started_at REAL, finished_at REAL,
            duration_ms INTEGER
        );
        CREATE TABLE orchestration_runs (
            orchestration_uuid TEXT PRIMARY KEY, orchestration_name TEXT,
            message TEXT, status TEXT, output_text TEXT, error_message TEXT,
            started_at REAL, finished_at REAL, duration_ms INTEGER
        );
        INSERT INTO agent_runs (run_uuid, agent_name, source, status, input_message, duration_ms, started_at)
        VALUES ('r1', 'researcher', 'manual', 'success', 'Research topic', 1500, 1700000000.0);
        INSERT INTO agent_runs (run_uuid, agent_name, source, status, input_message, duration_ms, started_at)
        VALUES ('r2', 'writer', 'delegation', 'success', 'Write summary', 800, 1700000001.0);
        INSERT INTO orchestration_runs (orchestration_uuid, orchestration_name, message, status, duration_ms, started_at)
        VALUES ('o1', 'research_flow', 'Summarize AI', 'success', 3000, 1700000000.0);
    """)
    conn.commit()
    conn.close()
    yield db_path
    if db_path.exists():
        db_path.unlink()


def test_read_logs_returns_agent_runs(events_db):
    """_read_logs returns agent run rows ordered by started_at DESC."""
    rows = _read_logs(events_db, limit=10)
    assert len(rows) == 2
    # Order: writer (started_at 1700000001) before researcher (1700000000)
    agent_names = [r[0] for r in rows]
    assert agent_names == ["writer", "researcher"]


def test_read_logs_filter_by_agent(events_db):
    """_read_logs filters by agent_name when provided."""
    rows = _read_logs(events_db, agent="researcher", limit=10)
    assert len(rows) == 1
    assert rows[0][0] == "researcher"


def test_read_logs_filter_by_status(events_db):
    """_read_logs filters by status when provided."""
    rows = _read_logs(events_db, status="success", limit=10)
    assert len(rows) == 2


def test_read_orchestration_logs_returns_orchestration_runs(events_db):
    """_read_orchestration_logs returns orchestration run rows."""
    rows = _read_orchestration_logs(events_db, limit=10)
    assert len(rows) == 1
    assert rows[0][0] == "research_flow"  # orchestration_name
    assert rows[0][1] == "success"  # status
    assert rows[0][2] == "Summarize AI"  # message


def test_read_orchestration_logs_filter_by_name(events_db):
    """_read_orchestration_logs filters by orchestration_name when provided."""
    rows = _read_orchestration_logs(events_db, orchestration="research_flow", limit=10)
    assert len(rows) == 1
    assert rows[0][0] == "research_flow"


# --------------------------------------------------------------------------- #
# ez logs CLI
# --------------------------------------------------------------------------- #


def test_logs_cli_shows_agent_runs():
    """ez logs shows agent run logs when run from project dir."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Create project structure in isolated fs
        project_dir = Path.cwd()
        (project_dir / "agents.yml").write_text("""
agents:
  researcher:
    description: Researcher agent
  writer:
    description: Writer agent
""")
        ezagent_dir = project_dir / ".ezagent"
        ezagent_dir.mkdir()
        # Copy events from fixture (we need the db from events_db fixture)
        # Create minimal db inline since we can't easily share fixtures
        db_path = ezagent_dir / "events.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE agent_runs (
                run_uuid TEXT PRIMARY KEY, agent_name TEXT, input_message TEXT,
                output_text TEXT, status TEXT, error_message TEXT, depth INTEGER,
                source TEXT, parent_run_uuid TEXT, started_at REAL, finished_at REAL,
                duration_ms INTEGER
            );
            INSERT INTO agent_runs (run_uuid, agent_name, source, status, input_message, duration_ms, started_at)
            VALUES ('r1', 'researcher', 'manual', 'success', 'Research topic', 1500, 1700000000.0);
        """)
        conn.commit()
        conn.close()

        result = runner.invoke(cli, ["logs", "--limit", "5"])

    assert result.exit_code == 0
    assert "researcher" in result.output
    assert "AGENT" in result.output


def test_logs_cli_no_project_exits_with_error():
    """ez logs raises when run outside a project (no agents.yml)."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        # Empty temp dir, no agents.yml
        result = runner.invoke(cli, ["logs"])
    assert result.exit_code != 0
    assert "agents.yml" in result.output or "project" in result.output.lower()
