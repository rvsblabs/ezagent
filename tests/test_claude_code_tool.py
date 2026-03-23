"""Tests for the claude_code prebuilt tool."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: redirect session state file to a temp home for every test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_state_file(tmp_path, monkeypatch):
    """Redirect session state file to a temp directory for every test."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    real_expanduser = Path.expanduser

    def patched_expanduser(self):
        s = str(self)
        if s.startswith("~"):
            return Path(str(fake_home) + s[1:])
        return real_expanduser(self)

    monkeypatch.setattr(Path, "expanduser", patched_expanduser)
    yield fake_home


# ---------------------------------------------------------------------------
# sessions.py unit tests
# ---------------------------------------------------------------------------

def test_get_session_returns_none_when_no_state_file():
    from ezagent.tools.builtins.claude_code.sessions import get_session
    result = get_session("/some/dir")
    assert result is None


def test_save_and_get_session(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import get_session, save_session
    directory = str(tmp_path / "repo")
    save_session(directory, "test-uuid-1234")
    assert get_session(directory) == "test-uuid-1234"


def test_get_session_unknown_directory(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import get_session, save_session
    save_session(str(tmp_path / "repo-a"), "uuid-a")
    assert get_session(str(tmp_path / "repo-b")) is None


def test_clear_session_returns_true_when_existed(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import clear_session, save_session
    directory = str(tmp_path / "repo")
    save_session(directory, "some-uuid")
    assert clear_session(directory) is True


def test_clear_session_returns_false_when_not_found(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import clear_session
    assert clear_session(str(tmp_path / "nonexistent")) is False


def test_clear_session_removes_entry(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import clear_session, get_session, save_session
    directory = str(tmp_path / "repo")
    save_session(directory, "uuid-to-remove")
    clear_session(directory)
    assert get_session(directory) is None


def test_state_file_created_in_ezagent_dir(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import _state_path, save_session
    save_session(str(tmp_path / "repo"), "uuid")
    p = _state_path()
    assert p.exists()
    assert p.name == "claude_code_sessions.json"
    assert p.parent.name == ".ezagent"


def test_save_session_degrades_gracefully_on_io_error(tmp_path):
    """If the state file cannot be written, save_session logs and returns without raising."""
    from ezagent.tools.builtins.claude_code.sessions import save_session
    directory = str(tmp_path / "repo")
    with patch("pathlib.Path.write_text", side_effect=OSError("disk full")):
        # Should not raise
        save_session(directory, "uuid-1234")


def test_concurrent_writes_do_not_corrupt(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import get_session, save_session

    errors = []

    def write_session(idx):
        try:
            directory = str(tmp_path / f"repo-{idx}")
            save_session(directory, f"uuid-{idx}")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=write_session, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    for i in range(20):
        directory = str(tmp_path / f"repo-{i}")
        assert get_session(directory) == f"uuid-{i}"
