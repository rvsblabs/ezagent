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
    """Redirect session state to a temp directory for every test."""
    state_file = tmp_path / ".ezagent" / "claude_code_sessions.json"

    def fake_state_path():
        state_file.parent.mkdir(parents=True, exist_ok=True)
        return state_file

    monkeypatch.setattr(
        "ezagent.tools.builtins.claude_code.sessions._state_path",
        fake_state_path,
    )
    yield state_file


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


# ---------------------------------------------------------------------------
# main.py — helpers and validation/reset tests
# ---------------------------------------------------------------------------

def _call_tool(tool_name: str, **kwargs):
    """Import and call a tool function from main.py directly."""
    import importlib
    import sys

    # Preserve the sessions module object (which has monkeypatches applied by
    # the isolated_state_file fixture) across the main.py module eviction.
    sessions_key = "ezagent.tools.builtins.claude_code.sessions"
    sessions_mod = sys.modules.get(sessions_key)

    # Evict main.py only (not sessions) so monkeypatches survive reimport.
    for mod_name in list(sys.modules.keys()):
        if "claude_code.main" in mod_name:
            del sys.modules[mod_name]

    # Re-register sessions under the bare "sessions" key so main.py's
    # `sys.path.insert + import sessions` finds the patched module object.
    if sessions_mod is not None:
        sys.modules["sessions"] = sessions_mod

    mod = importlib.import_module("ezagent.tools.builtins.claude_code.main")
    fn = getattr(mod, tool_name)
    return json.loads(fn(**kwargs))


def _make_proc(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


CLAUDE_RESPONSE = json.dumps({
    "result": "I fixed the bug in auth.py.",
    "session_id": "abc-123-def",
})


def test_run_rejects_relative_directory():
    result = _call_tool("run", directory="relative/path", message="hello")
    assert "error" in result
    assert "absolute" in result["error"].lower()


def test_run_rejects_nonexistent_directory(tmp_path):
    result = _call_tool("run", directory=str(tmp_path / "does_not_exist"), message="hello")
    assert "error" in result
    assert "does not exist" in result["error"].lower()


def test_run_rejects_invalid_permission_mode(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("run", directory=str(d), message="hello", permission_mode="invalid")
    assert "error" in result
    assert "permission_mode" in result["error"].lower()


def test_reset_returns_not_found_when_no_session(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("reset", directory=str(d))
    assert result["status"] == "not_found"
    assert result["directory"] == str(d)


def test_reset_clears_existing_session(tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import save_session
    d = tmp_path / "repo"
    d.mkdir()
    save_session(str(d), "some-uuid")
    result = _call_tool("reset", directory=str(d))
    assert result["status"] == "reset"
    assert result["directory"] == str(d)


def test_reset_rejects_relative_directory():
    result = _call_tool("reset", directory="relative/path")
    assert "error" in result


# ---------------------------------------------------------------------------
# main.py — run tool subprocess logic (mocked claude)
# ---------------------------------------------------------------------------

@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_creates_new_session(mock_run, mock_which, tmp_path):
    mock_run.return_value = _make_proc(stdout=CLAUDE_RESPONSE)
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("run", directory=str(d), message="fix the bug")
    assert result["session_id"] == "abc-123-def"
    assert result["session_reset"] is False
    assert "fixed the bug" in result["output"]
    # Verify --resume was NOT passed (new session)
    cmd = mock_run.call_args[0][0]
    assert "--resume" not in cmd


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_resumes_existing_session(mock_run, mock_which, tmp_path):
    from ezagent.tools.builtins.claude_code.sessions import save_session
    d = tmp_path / "repo"
    d.mkdir()
    save_session(str(d), "existing-session-id")
    mock_run.return_value = _make_proc(stdout=CLAUDE_RESPONSE)
    result = _call_tool("run", directory=str(d), message="continue")
    cmd = mock_run.call_args[0][0]
    assert "--resume" in cmd
    assert "existing-session-id" in cmd


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_retries_on_stale_session(mock_run, mock_which, tmp_path):
    """First call fails (stale session), second succeeds as new session."""
    from ezagent.tools.builtins.claude_code.sessions import get_session, save_session
    d = tmp_path / "repo"
    d.mkdir()
    save_session(str(d), "stale-session-id")
    mock_run.side_effect = [
        _make_proc(returncode=1, stderr="session not found"),
        _make_proc(stdout=CLAUDE_RESPONSE),
    ]
    result = _call_tool("run", directory=str(d), message="try again")
    assert result["session_reset"] is True
    assert result["session_id"] == "abc-123-def"
    assert get_session(str(d)) == "abc-123-def"


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_surfaces_error_when_retry_fails(mock_run, mock_which, tmp_path):
    """Both calls fail: error returned, stale entry cleared."""
    from ezagent.tools.builtins.claude_code.sessions import get_session, save_session
    d = tmp_path / "repo"
    d.mkdir()
    save_session(str(d), "stale-session-id")
    mock_run.side_effect = [
        _make_proc(returncode=1, stderr="session not found"),
        _make_proc(returncode=1, stderr="another error"),
    ]
    result = _call_tool("run", directory=str(d), message="try again")
    assert "error" in result
    # Stale entry must be cleared even after retry failure
    assert get_session(str(d)) is None


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_truncates_long_output(mock_run, mock_which, tmp_path):
    long_output = "x" * 60_000
    response = json.dumps({"result": long_output, "session_id": "s1"})
    mock_run.return_value = _make_proc(stdout=response)
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("run", directory=str(d), message="go")
    assert len(result["output"]) <= 50_000 + len("\n\n[Output truncated]")
    assert result["output"].endswith("[Output truncated]")


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run")
def test_run_handles_non_json_output(mock_run, mock_which, tmp_path):
    mock_run.return_value = _make_proc(stdout="some plain text output")
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("run", directory=str(d), message="go")
    assert result["output"] == "some plain text output"
    assert result["session_id"] is None
    assert "parse_warning" in result


@patch("shutil.which", return_value=None)
def test_run_errors_when_claude_not_found(mock_which, tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    # Patch is_file only for the claude fallback path, not for Path.exists
    original_is_file = Path.is_file

    def patched_is_file(self):
        if "local/bin/claude" in str(self):
            return False
        return original_is_file(self)

    with patch.object(Path, "is_file", patched_is_file):
        result = _call_tool("run", directory=str(d), message="go")
    assert "error" in result
    assert "claude CLI not found" in result["error"]


@patch("shutil.which", return_value="/usr/local/bin/claude")
@patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=600))
def test_run_returns_error_on_timeout(mock_run, mock_which, tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("run", directory=str(d), message="go")
    assert "timed out" in result["error"]
