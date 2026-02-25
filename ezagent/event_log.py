from __future__ import annotations

import asyncio
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="event_log")


def _now() -> float:
    return time.time()


def _new_uuid() -> str:
    return str(uuid.uuid4())


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agent_runs (
            run_uuid        TEXT PRIMARY KEY,
            agent_name      TEXT,
            input_message   TEXT,
            output_text     TEXT,
            status          TEXT DEFAULT 'running',
            error_message   TEXT,
            depth           INTEGER,
            source          TEXT,
            parent_run_uuid TEXT,
            started_at      REAL,
            finished_at     REAL,
            duration_ms     INTEGER
        );

        CREATE TABLE IF NOT EXISTS tool_invocations (
            call_uuid     TEXT PRIMARY KEY,
            run_uuid      TEXT,
            tool_name     TEXT,
            input_json    TEXT,
            output_text   TEXT,
            status        TEXT,
            error_message TEXT,
            started_at    REAL,
            finished_at   REAL,
            duration_ms   INTEGER
        );

        CREATE TABLE IF NOT EXISTS llm_calls (
            call_uuid      TEXT PRIMARY KEY,
            run_uuid       TEXT,
            call_number    INTEGER,
            output_text    TEXT,
            tool_calls_json TEXT,
            stop_reason    TEXT,
            started_at     REAL,
            finished_at    REAL,
            duration_ms    INTEGER
        );

        CREATE TABLE IF NOT EXISTS discussion_runs (
            discussion_uuid TEXT PRIMARY KEY,
            discussion_name TEXT,
            topic           TEXT,
            status          TEXT DEFAULT 'running',
            terminal_state  TEXT,
            decision        TEXT,
            dissent         TEXT,
            rounds_completed INTEGER,
            started_at      REAL,
            finished_at     REAL,
            duration_ms     INTEGER
        );

        CREATE TABLE IF NOT EXISTS discussion_turns (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_uuid TEXT,
            agent_name      TEXT,
            role            TEXT,
            content         TEXT,
            round_number    INTEGER,
            created_at      REAL
        );

        CREATE TABLE IF NOT EXISTS orchestration_runs (
            orchestration_uuid TEXT PRIMARY KEY,
            orchestration_name TEXT,
            message          TEXT,
            status           TEXT DEFAULT 'running',
            output_text      TEXT,
            error_message    TEXT,
            started_at       REAL,
            finished_at      REAL,
            duration_ms      INTEGER
        );
    """)
    conn.commit()


class EventLogger:
    """Writes agent events to a SQLite database. Fire-and-forget for finish_* methods."""

    def __init__(self):
        self._db_path: Optional[Path] = None
        self._conn: Optional[sqlite3.Connection] = None

    def setup(self, db_path: Path) -> None:
        """Create tables. Called once synchronously at daemon start."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _create_tables(self._conn)

    def _conn_required(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("EventLogger.setup() must be called before use")
        return self._conn

    async def _await_sync(self, fn) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(_executor, fn)

    def _fire(self, fn) -> None:
        """Schedule a DB write as fire-and-forget."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._await_sync(fn))
            else:
                fn()
        except RuntimeError:
            fn()

    # ------------------------------------------------------------------ #
    # Agent runs
    # ------------------------------------------------------------------ #

    async def start_agent_run(
        self,
        agent_name: str,
        message: str,
        source: str = "manual",
        depth: int = 0,
        parent_run_uuid: Optional[str] = None,
    ) -> str:
        run_uuid = _new_uuid()
        started_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO agent_runs
                   (run_uuid, agent_name, input_message, status, depth, source,
                    parent_run_uuid, started_at)
                   VALUES (?, ?, ?, 'running', ?, ?, ?, ?)""",
                (run_uuid, agent_name, message, depth, source, parent_run_uuid, started_at),
            )
            conn.commit()

        await self._await_sync(_write)
        return run_uuid

    def finish_agent_run(
        self,
        run_uuid: str,
        output: str = "",
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        finished_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """UPDATE agent_runs
                   SET output_text=?, status=?, error_message=?,
                       finished_at=?,
                       duration_ms=CAST((? - started_at) * 1000 AS INTEGER)
                   WHERE run_uuid=?""",
                (output, status, error, finished_at, finished_at, run_uuid),
            )
            conn.commit()

        self._fire(_write)

    # ------------------------------------------------------------------ #
    # Tool invocations
    # ------------------------------------------------------------------ #

    async def start_tool_call(
        self, run_uuid: str, tool_name: str, input_json: str
    ) -> str:
        call_uuid = _new_uuid()
        started_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO tool_invocations
                   (call_uuid, run_uuid, tool_name, input_json, status, started_at)
                   VALUES (?, ?, ?, ?, 'running', ?)""",
                (call_uuid, run_uuid, tool_name, input_json, started_at),
            )
            conn.commit()

        await self._await_sync(_write)
        return call_uuid

    def finish_tool_call(
        self,
        call_uuid: str,
        output: str = "",
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        finished_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """UPDATE tool_invocations
                   SET output_text=?, status=?, error_message=?,
                       finished_at=?,
                       duration_ms=CAST((? - started_at) * 1000 AS INTEGER)
                   WHERE call_uuid=?""",
                (output, status, error, finished_at, finished_at, call_uuid),
            )
            conn.commit()

        self._fire(_write)

    # ------------------------------------------------------------------ #
    # LLM calls
    # ------------------------------------------------------------------ #

    async def start_llm_call(self, run_uuid: str, call_number: int) -> str:
        call_uuid = _new_uuid()
        started_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO llm_calls
                   (call_uuid, run_uuid, call_number, started_at)
                   VALUES (?, ?, ?, ?)""",
                (call_uuid, run_uuid, call_number, started_at),
            )
            conn.commit()

        await self._await_sync(_write)
        return call_uuid

    def finish_llm_call(
        self,
        call_uuid: str,
        output_text: str = "",
        tool_calls_json: Optional[str] = None,
        stop_reason: Optional[str] = None,
    ) -> None:
        finished_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """UPDATE llm_calls
                   SET output_text=?, tool_calls_json=?, stop_reason=?,
                       finished_at=?,
                       duration_ms=CAST((? - started_at) * 1000 AS INTEGER)
                   WHERE call_uuid=?""",
                (output_text, tool_calls_json, stop_reason, finished_at, finished_at, call_uuid),
            )
            conn.commit()

        self._fire(_write)

    # ------------------------------------------------------------------ #
    # Orchestration runs
    # ------------------------------------------------------------------ #

    async def start_orchestration_run(
        self, orchestration_name: str, message: str
    ) -> str:
        orchestration_uuid = _new_uuid()
        started_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO orchestration_runs
                   (orchestration_uuid, orchestration_name, message, status, started_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (orchestration_uuid, orchestration_name, message, started_at),
            )
            conn.commit()

        await self._await_sync(_write)
        return orchestration_uuid

    def finish_orchestration_run(
        self,
        orchestration_uuid: str,
        output_text: str = "",
        status: str = "success",
        error: Optional[str] = None,
    ) -> None:
        finished_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """UPDATE orchestration_runs
                   SET output_text=?, status=?, error_message=?,
                       finished_at=?,
                       duration_ms=CAST((? - started_at) * 1000 AS INTEGER)
                   WHERE orchestration_uuid=?""",
                (output_text, status, error, finished_at, finished_at, orchestration_uuid),
            )
            conn.commit()

        self._fire(_write)

    # ------------------------------------------------------------------ #
    # Discussion runs
    # ------------------------------------------------------------------ #

    async def start_discussion(self, discussion_name: str, topic: str) -> str:
        discussion_uuid = _new_uuid()
        started_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO discussion_runs
                   (discussion_uuid, discussion_name, topic, status, started_at)
                   VALUES (?, ?, ?, 'running', ?)""",
                (discussion_uuid, discussion_name, topic, started_at),
            )
            conn.commit()

        await self._await_sync(_write)
        return discussion_uuid

    def finish_discussion(
        self,
        discussion_uuid: str,
        terminal_state: str = "",
        decision: str = "",
        dissent: Optional[str] = None,
        rounds: int = 0,
        status: str = "success",
    ) -> None:
        finished_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """UPDATE discussion_runs
                   SET status=?, terminal_state=?, decision=?, dissent=?,
                       rounds_completed=?, finished_at=?,
                       duration_ms=CAST((? - started_at) * 1000 AS INTEGER)
                   WHERE discussion_uuid=?""",
                (
                    status, terminal_state, decision, dissent, rounds,
                    finished_at, finished_at, discussion_uuid,
                ),
            )
            conn.commit()

        self._fire(_write)

    def log_discussion_turn(
        self,
        discussion_uuid: str,
        agent_name: str,
        role: str,
        content: str,
        round_number: int,
    ) -> None:
        created_at = _now()

        def _write():
            conn = self._conn_required()
            conn.execute(
                """INSERT INTO discussion_turns
                   (discussion_uuid, agent_name, role, content, round_number, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (discussion_uuid, agent_name, role, content, round_number, created_at),
            )
            conn.commit()

        self._fire(_write)
