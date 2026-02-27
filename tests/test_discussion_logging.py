"""Tests for DiscussionRuntime event logging integration."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict
from unittest.mock import AsyncMock

import pytest

from ezagent.agent import Agent, AgentResult
from ezagent.config import AgentConfig, DiscussantConfig, DiscussionConfig
from ezagent.discussion import DiscussionRuntime
from ezagent.event_log import EventLogger
from ezagent.llm.base import LLMProvider, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rows(db_path: Path, table: str) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]
    finally:
        conn.close()


def _make_logger(tmp_path: Path) -> tuple[EventLogger, Path]:
    db_path = tmp_path / ".ezagent" / "events.db"
    el = EventLogger()
    el.setup(db_path)
    return el, db_path


class FixedLLM(LLMProvider):
    def __init__(self, text: str):
        self._text = text

    async def chat(self, messages, system="", tools=None) -> LLMResponse:
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="end_turn")


def _make_mock_agent(name: str, response: str, event_logger=None) -> Agent:
    config = AgentConfig(description=name)
    agent = Agent(
        name=name,
        config=config,
        project_dir=Path("/tmp"),
        provider=FixedLLM(response),
        agent_names=[],
        event_logger=event_logger,
    )
    return agent


def _two_round_config(termination: str = "rounds") -> DiscussionConfig:
    return DiscussionConfig(
        participants=[
            DiscussantConfig(agent="alice", role="advocate"),
            DiscussantConfig(agent="bob", role="critic"),
        ],
        max_rounds=2,
        termination=termination,
        on_deadlock=["record_and_move_on"],
    )


import asyncio


# ---------------------------------------------------------------------------
# discussion_runs table
# ---------------------------------------------------------------------------

async def test_start_discussion_creates_row(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "I think X"),
        "bob": _make_mock_agent("bob", "I disagree"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "stuck", "dissenters": []}')
    runtime = DiscussionRuntime("planning", config, agents, checker, event_logger=el)

    await runtime.run("what to build?")
    await asyncio.sleep(0.05)

    rows = _rows(db_path, "discussion_runs")
    assert len(rows) == 1
    r = rows[0]
    assert r["discussion_name"] == "planning"
    assert r["topic"] == "what to build?"
    assert r["status"] == "success"
    assert r["rounds_completed"] == 2
    assert r["terminal_state"] is not None
    assert r["duration_ms"] is not None


async def test_discussion_uuid_is_unique_per_run(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "yes"),
        "bob": _make_mock_agent("bob", "no"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')

    runtime1 = DiscussionRuntime("d", config, agents, checker, event_logger=el)
    runtime2 = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime1.run("topic 1")
    await runtime2.run("topic 2")
    await asyncio.sleep(0.05)

    rows = _rows(db_path, "discussion_runs")
    assert len(rows) == 2
    uuids = [r["discussion_uuid"] for r in rows]
    assert uuids[0] != uuids[1]


# ---------------------------------------------------------------------------
# discussion_turns table
# ---------------------------------------------------------------------------

async def test_turns_logged_per_participant_per_round(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "alice says"),
        "bob": _make_mock_agent("bob", "bob says"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime.run("topic")
    await asyncio.sleep(0.05)

    turns = _rows(db_path, "discussion_turns")
    # 2 participants × 2 rounds = 4 turns
    assert len(turns) == 4
    agent_names = [t["agent_name"] for t in turns]
    assert agent_names.count("alice") == 2
    assert agent_names.count("bob") == 2


async def test_turns_have_correct_round_numbers(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "a"),
        "bob": _make_mock_agent("bob", "b"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime.run("topic")
    await asyncio.sleep(0.05)

    turns = _rows(db_path, "discussion_turns")
    round_numbers = {t["round_number"] for t in turns}
    assert round_numbers == {1, 2}


async def test_turns_have_correct_roles(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "a"),
        "bob": _make_mock_agent("bob", "b"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime.run("topic")
    await asyncio.sleep(0.05)

    turns = _rows(db_path, "discussion_turns")
    roles = {t["agent_name"]: t["role"] for t in turns}
    assert roles["alice"] == "advocate"
    assert roles["bob"] == "critic"


async def test_turns_reference_discussion_uuid(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "a"),
        "bob": _make_mock_agent("bob", "b"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime.run("topic")
    await asyncio.sleep(0.05)

    disc_uuid = _rows(db_path, "discussion_runs")[0]["discussion_uuid"]
    turns = _rows(db_path, "discussion_turns")
    assert all(t["discussion_uuid"] == disc_uuid for t in turns)


# ---------------------------------------------------------------------------
# participant agent runs have source="discussion" and parent_run_uuid set
# ---------------------------------------------------------------------------

async def test_participant_agent_runs_have_discussion_source(tmp_path: Path):
    el, db_path = _make_logger(tmp_path)
    config = DiscussionConfig(
        participants=[DiscussantConfig(agent="alice", role="r")],
        max_rounds=1,
        termination="rounds",
        on_deadlock=["record_and_move_on"],
    )
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "response", event_logger=el),
    }
    # Simple moderator synthesis: we need alice as moderator too
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "s", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=el)

    await runtime.run("topic")
    await asyncio.sleep(0.1)

    agent_rows = _rows(db_path, "agent_runs")
    disc_uuid = _rows(db_path, "discussion_runs")[0]["discussion_uuid"]

    # Alice's run (as participant) should have source=discussion
    participant_runs = [r for r in agent_rows if r["agent_name"] == "alice" and r["source"] == "discussion"]
    assert len(participant_runs) >= 1
    assert all(r["parent_run_uuid"] == disc_uuid for r in participant_runs)


# ---------------------------------------------------------------------------
# DiscussionRuntime works without event_logger
# ---------------------------------------------------------------------------

async def test_discussion_works_without_event_logger():
    config = _two_round_config()
    agents: Dict[str, Agent] = {
        "alice": _make_mock_agent("alice", "I think X"),
        "bob": _make_mock_agent("bob", "I disagree"),
    }
    checker = FixedLLM('{"converged": false, "type": "deadlock", "summary": "stuck", "dissenters": []}')
    runtime = DiscussionRuntime("d", config, agents, checker, event_logger=None)

    result = await runtime.run("topic")
    assert result.topic == "topic"
    assert result.rounds_completed == 2
