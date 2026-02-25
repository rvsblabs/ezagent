"""Tests for orchestration event logging."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ezagent.event_log import EventLogger


@pytest.fixture
def event_logger():
    """EventLogger with temp DB."""
    db_path = Path(tempfile.mktemp(suffix=".db"))
    logger = EventLogger()
    logger.setup(db_path)
    yield logger
    if db_path.exists():
        db_path.unlink()


@pytest.mark.asyncio
async def test_start_and_finish_orchestration_run(event_logger):
    """Orchestration run is logged to orchestration_runs table."""
    orch_uuid = await event_logger.start_orchestration_run(
        "research_flow", "Summarize AI safety"
    )
    assert orch_uuid

    event_logger.finish_orchestration_run(
        orch_uuid,
        output_text="Final synthesized answer",
        status="success",
    )
    # Give fire-and-forget time to run
    import asyncio
    await asyncio.sleep(0.2)

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT orchestration_name, message, output_text, status FROM orchestration_runs WHERE orchestration_uuid = ?",
        (orch_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "research_flow"
    assert row[1] == "Summarize AI safety"
    assert row[2] == "Final synthesized answer"
    assert row[3] == "success"


@pytest.mark.asyncio
async def test_orchestration_runs_table_exists(event_logger):
    """orchestration_runs table is created on setup."""
    conn = sqlite3.connect(str(event_logger._db_path))
    tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    conn.close()
    assert "orchestration_runs" in tables
