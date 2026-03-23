"""Session registry for the claude_code prebuilt tool.

Maps absolute directory paths -> Claude Code session UUIDs.
State is persisted to ~/.ezagent/claude_code_sessions.json.
All reads/writes use filelock to prevent corruption under parallel access.
If the state file cannot be written (e.g. disk full), operations degrade
gracefully — the tool still returns output, just without session persistence.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from filelock import FileLock

logger = logging.getLogger(__name__)


def _state_path() -> Path:
    """Return path to the session state file (no side effects)."""
    return Path("~/.ezagent").expanduser() / "claude_code_sessions.json"


def _lock_path() -> Path:
    return _state_path().with_suffix(".lock")


def _load() -> dict[str, str]:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, str]) -> None:
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except OSError as e:
        logger.warning("claude_code: could not write session state: %s", e)


def get_session(directory: str) -> str | None:
    """Return session ID for *directory*, or None if not found."""
    with FileLock(str(_lock_path())):
        return _load().get(directory)


def save_session(directory: str, session_id: str) -> None:
    """Persist *session_id* for *directory*. Degrades gracefully on I/O error."""
    with FileLock(str(_lock_path())):
        data = _load()
        data[directory] = session_id
        _save(data)


def clear_session(directory: str) -> bool:
    """Remove session entry for *directory*.

    Returns True if the entry existed at read time; removal is best-effort
    (write errors are logged but not raised).
    """
    with FileLock(str(_lock_path())):
        data = _load()
        if directory not in data:
            return False
        del data[directory]
        _save(data)
        return True
