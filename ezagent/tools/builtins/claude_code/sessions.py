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


# ---------------------------------------------------------------------------
# Self-register under the bare "sessions" key in sys.modules.
#
# When this module is first imported via the full package path
# (ezagent.tools.builtins.claude_code.sessions), it also registers itself
# under the bare "sessions" key.  This ensures that when main.py is reimported
# in an isolated test environment (after the "claude_code" entries are evicted
# from sys.modules by _call_tool), its `import sessions` statement hits the
# SAME cached module object — including any monkeypatches applied by test
# fixtures — rather than re-executing the module from disk.
# ---------------------------------------------------------------------------
import sys as _sys

# Always keep the bare "sessions" key in sys.modules pointing to THIS module
# object.  When main.py runs `import sessions` (via sys.path insert), Python
# returns the cached entry from sys.modules — meaning it gets EXACTLY this
# module, including any monkeypatches applied by test fixtures.
#
# Why always overwrite (not just set-if-missing): _call_tool in tests evicts all
# "claude_code" entries from sys.modules and then reimports main.py, which
# triggers a fresh re-execution of sessions.py.  On that reimport the new module
# object is different from the old one that fixtures patched.  By always writing
# the current module into sys.modules["sessions"], we ensure that subsequent
# `import sessions` calls (from a freshly-imported main.py) get the same fresh
# object that the fixture is about to patch — not a stale prior one.
_sys.modules["sessions"] = _sys.modules[__name__]
