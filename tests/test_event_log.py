"""EventLogger unit tests for all tables (agent_runs, tool_invocations, llm_calls, discussion_runs, discussion_turns)."""

import asyncio
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


async def _wait_for_fire_and_forget():
    """Allow fire-and-forget DB writes to complete."""
    await asyncio.sleep(0.2)


# --------------------------------------------------------------------------- #
# Agent runs
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_and_finish_agent_run(event_logger):
    """Agent run is logged to agent_runs table."""
    run_uuid = await event_logger.start_agent_run(
        "researcher", "Summarize AI safety", source="manual", depth=0
    )
    assert run_uuid

    event_logger.finish_agent_run(run_uuid, output="Done", status="success")
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT agent_name, input_message, output_text, status, source FROM agent_runs WHERE run_uuid = ?",
        (run_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "researcher"
    assert row[1] == "Summarize AI safety"
    assert row[2] == "Done"
    assert row[3] == "success"
    assert row[4] == "manual"


@pytest.mark.asyncio
async def test_agent_run_with_delegation(event_logger):
    """Agent run with parent_run_uuid (delegation) is logged."""
    parent_uuid = await event_logger.start_agent_run(
        "planner", "Plan research", source="manual"
    )
    child_uuid = await event_logger.start_agent_run(
        "researcher", "Do subtask", source="delegation", depth=1, parent_run_uuid=parent_uuid
    )
    assert child_uuid != parent_uuid

    event_logger.finish_agent_run(child_uuid, output="Subtask done", status="success")
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT parent_run_uuid, depth, source FROM agent_runs WHERE run_uuid = ?",
        (child_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == parent_uuid
    assert row[1] == 1
    assert row[2] == "delegation"


# --------------------------------------------------------------------------- #
# Tool invocations
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_and_finish_tool_call(event_logger):
    """Tool call is logged to tool_invocations table."""
    run_uuid = await event_logger.start_agent_run("assistant", "Hi", source="manual")
    call_uuid = await event_logger.start_tool_call(
        run_uuid, "web_search", '{"query": "AI news"}'
    )
    assert call_uuid

    event_logger.finish_tool_call(call_uuid, output="Search results", status="success")
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT run_uuid, tool_name, input_json, output_text, status FROM tool_invocations WHERE call_uuid = ?",
        (call_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == run_uuid
    assert row[1] == "web_search"
    assert row[2] == '{"query": "AI news"}'
    assert row[3] == "Search results"
    assert row[4] == "success"


@pytest.mark.asyncio
async def test_tool_call_error(event_logger):
    """Tool call with error status is logged."""
    run_uuid = await event_logger.start_agent_run("assistant", "Hi", source="manual")
    call_uuid = await event_logger.start_tool_call(run_uuid, "http", "{}")
    event_logger.finish_tool_call(
        call_uuid, output="", status="error", error="Connection refused"
    )
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT status, error_message FROM tool_invocations WHERE call_uuid = ?",
        (call_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "error"
    assert row[1] == "Connection refused"


# --------------------------------------------------------------------------- #
# LLM calls
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_and_finish_llm_call(event_logger):
    """LLM call is logged to llm_calls table."""
    run_uuid = await event_logger.start_agent_run("assistant", "Hi", source="manual")
    call_uuid = await event_logger.start_llm_call(run_uuid, call_number=1)
    assert call_uuid

    event_logger.finish_llm_call(
        call_uuid,
        output_text="Hello!",
        tool_calls_json="[]",
        stop_reason="end_turn",
    )
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT run_uuid, call_number, output_text, tool_calls_json, stop_reason FROM llm_calls WHERE call_uuid = ?",
        (call_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == run_uuid
    assert row[1] == 1
    assert row[2] == "Hello!"
    assert row[3] == "[]"
    assert row[4] == "end_turn"


# --------------------------------------------------------------------------- #
# Discussion runs
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_start_and_finish_discussion(event_logger):
    """Discussion run is logged to discussion_runs table."""
    disc_uuid = await event_logger.start_discussion("design_review", "API design")
    assert disc_uuid

    event_logger.finish_discussion(
        disc_uuid,
        terminal_state="consensus",
        decision="Use REST",
        dissent=None,
        rounds=3,
        status="success",
    )
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT discussion_name, topic, status, terminal_state, decision, rounds_completed FROM discussion_runs WHERE discussion_uuid = ?",
        (disc_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "design_review"
    assert row[1] == "API design"
    assert row[2] == "success"
    assert row[3] == "consensus"
    assert row[4] == "Use REST"
    assert row[5] == 3


# --------------------------------------------------------------------------- #
# Discussion turns
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_log_discussion_turn(event_logger):
    """Discussion turn is logged to discussion_turns table."""
    disc_uuid = await event_logger.start_discussion("debate", "Topic X")
    event_logger.log_discussion_turn(
        disc_uuid,
        agent_name="analyst",
        role="skeptic",
        content="I disagree because...",
        round_number=1,
    )
    await _wait_for_fire_and_forget()

    conn = sqlite3.connect(str(event_logger._db_path))
    row = conn.execute(
        "SELECT discussion_uuid, agent_name, role, content, round_number FROM discussion_turns WHERE discussion_uuid = ?",
        (disc_uuid,),
    ).fetchone()
    conn.close()

    assert row is not None
    assert row[0] == disc_uuid
    assert row[1] == "analyst"
    assert row[2] == "skeptic"
    assert row[3] == "I disagree because..."
    assert row[4] == 1


# --------------------------------------------------------------------------- #
# Lifecycle and isolation
# --------------------------------------------------------------------------- #


def test_setup_creates_all_tables(event_logger):
    """Setup creates all expected tables."""
    conn = sqlite3.connect(str(event_logger._db_path))
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    conn.close()

    assert "agent_runs" in tables
    assert "tool_invocations" in tables
    assert "llm_calls" in tables
    assert "discussion_runs" in tables
    assert "discussion_turns" in tables
    assert "orchestration_runs" in tables


def test_event_logger_requires_setup():
    """EventLogger raises if used before setup."""
    logger = EventLogger()
    with pytest.raises(RuntimeError, match="setup"):
        logger._conn_required()
