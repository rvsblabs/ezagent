# Claude Code Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `claude_code` prebuilt tool that lets ezagent agents spawn and drive multi-turn Claude Code sessions, keyed by directory, with persistent session state across agent runs.

**Architecture:** A FastMCP server (`main.py`) exposes two tools — `run` and `reset` — which agents see as `claude_code__run` and `claude_code__reset`. A separate `sessions.py` module handles loading, saving, and locking the session registry at `~/.ezagent/claude_code_sessions.json`. The tool spawns `claude -p` as a blocking subprocess and manages session IDs transparently. `main.py` uses a local path-based import for `sessions` because the tool runs as an isolated subprocess where the `ezagent` package is not installed.

**Tech Stack:** Python stdlib (`subprocess`, `shutil`, `json`, `pathlib`, `threading`), `fastmcp<3`, `filelock`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `ezagent/tools/builtins/claude_code/__init__.py` | Create (empty) | Makes directory a Python package for test imports |
| `ezagent/tools/builtins/claude_code/sessions.py` | Create | Session registry: load/save/lookup/clear with filelock concurrency |
| `ezagent/tools/builtins/claude_code/main.py` | Create | FastMCP server: `run` and `reset` tools, subprocess execution, validation |
| `ezagent/tools/builtins/claude_code/requirements.txt` | Create | `fastmcp<3` and `filelock` dependencies |
| `ezagent/tools/builtins/__init__.py` | Modify | Register `claude_code` in `PREBUILT_TOOLS` |
| `README.md` | Modify | Add `claude_code` row to prebuilt tools table |
| `tests/test_claude_code_tool.py` | Create | Unit tests (no claude CLI required) + integration tests (skipped if claude absent) |

---

## Task 1: Session Registry (`sessions.py`)

**Files:**
- Create: `ezagent/tools/builtins/claude_code/__init__.py`
- Create: `ezagent/tools/builtins/claude_code/sessions.py`
- Create: `ezagent/tools/builtins/claude_code/requirements.txt`
- Create: `tests/test_claude_code_tool.py`

### Background

`sessions.py` is a standalone module that manages `~/.ezagent/claude_code_sessions.json`. It maps absolute directory paths to Claude Code session UUIDs. All reads/writes go through a `filelock` to prevent corruption when parallel agents run concurrently.

The module exposes four functions:
- `get_session(directory: str) -> str | None`
- `save_session(directory: str, session_id: str) -> None`
- `clear_session(directory: str) -> bool` — returns `True` if entry existed
- `_state_path() -> Path` — path to state file (used in tests)

**Important note on imports:** `main.py` is launched as an isolated subprocess by `UvStdioTransport`. The `ezagent` package is not installed in that subprocess environment. Therefore `main.py` imports `sessions` via a local path insert (`sys.path.insert(0, str(Path(__file__).parent))`), not via `ezagent.tools.builtins.claude_code.sessions`. Tests import via the full package path (`from ezagent.tools.builtins.claude_code.sessions import ...`) because `ezagent` is installed in the test environment — this is the correct pattern for all other prebuilt tools.

- [ ] **Step 1: Write the failing tests for `sessions.py`**

Create `tests/test_claude_code_tool.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/sarveshbhatnagar/Development/ezagent
uv run pytest tests/test_claude_code_tool.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'ezagent.tools.builtins.claude_code'`

- [ ] **Step 3: Create the package files**

```bash
mkdir -p ezagent/tools/builtins/claude_code
touch ezagent/tools/builtins/claude_code/__init__.py
```

Create `ezagent/tools/builtins/claude_code/requirements.txt`:

```
fastmcp<3
filelock>=3.12
```

Create `ezagent/tools/builtins/claude_code/sessions.py`:

```python
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
    """Return path to the session state file, creating parent dir if needed."""
    state_dir = Path("~/.ezagent").expanduser()
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "claude_code_sessions.json"


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
        _state_path().write_text(json.dumps(data, indent=2))
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
    """Remove session entry for *directory*. Returns True if entry existed."""
    with FileLock(str(_lock_path())):
        data = _load()
        if directory not in data:
            return False
        del data[directory]
        _save(data)
        return True
```

- [ ] **Step 4: Run sessions tests to verify they pass**

```bash
uv run pytest tests/test_claude_code_tool.py -v -k "session"
```

Expected: all 9 session tests pass.

- [ ] **Step 5: Commit**

```bash
git add ezagent/tools/builtins/claude_code/__init__.py \
        ezagent/tools/builtins/claude_code/sessions.py \
        ezagent/tools/builtins/claude_code/requirements.txt \
        tests/test_claude_code_tool.py
git commit -m "feat: add claude_code sessions registry with filelock concurrency"
```

---

## Task 2: FastMCP Server (`main.py`) — Validation & `reset`

**Files:**
- Create: `ezagent/tools/builtins/claude_code/main.py`
- Modify: `tests/test_claude_code_tool.py`

### Background

Build `main.py` incrementally. This task covers the FastMCP scaffold, input validation, and `reset` — no subprocess yet.

`main.py` imports `sessions` via a local `sys.path` insert because the tool runs as an isolated subprocess where `ezagent` is not installed:
```python
sys.path.insert(0, str(Path(__file__).parent))
import sessions
```

- [ ] **Step 1: Add validation and reset tests**

Append to `tests/test_claude_code_tool.py`:

```python
# ---------------------------------------------------------------------------
# main.py — helpers and validation/reset tests
# ---------------------------------------------------------------------------

def _call_tool(tool_name: str, **kwargs):
    """Import and call a tool function from main.py directly."""
    import importlib
    import sys
    # Fresh import each time so monkeypatched HOME affects the sessions module
    for mod_name in list(sys.modules.keys()):
        if "claude_code" in mod_name:
            del sys.modules[mod_name]
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
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
uv run pytest tests/test_claude_code_tool.py -v -k "run_rejects or reset"
```

Expected: `ModuleNotFoundError` or `AttributeError` — `main.py` does not exist yet.

- [ ] **Step 3: Create `main.py`**

Create `ezagent/tools/builtins/claude_code/main.py`:

```python
"""Prebuilt claude_code tool for ezagent.

Lets agents spawn and drive Claude Code (the `claude` CLI) for long-running,
multi-turn coding sessions. Sessions are keyed by directory and persist across
agent runs via ~/.ezagent/claude_code_sessions.json.

WARNING: The default permission_mode is 'bypassPermissions', which allows
Claude Code to edit files and run commands without prompting. Only use this
tool in directories you trust and control.

NOTE ON IMPORTS: This file uses a local sys.path insert for `sessions` because
main.py runs as an isolated subprocess (via UvStdioTransport) where the
`ezagent` package is NOT installed — only requirements.txt deps are available.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Local import: sessions.py lives alongside this file in the same directory.
# The ezagent package is not available in the isolated subprocess environment.
sys.path.insert(0, str(Path(__file__).parent))
import sessions  # noqa: E402

from fastmcp import FastMCP

mcp = FastMCP("claude_code")

MAX_OUTPUT_CHARS = 50_000

ALLOWED_PERMISSION_MODES = {
    "acceptEdits",
    "bypassPermissions",
    "default",
    "dontAsk",
    "plan",
    "auto",
}


def _find_claude() -> str | None:
    """Return path to the claude binary, or None if not found."""
    found = shutil.which("claude")
    if found:
        return found
    fallback = Path("~/.local/bin/claude").expanduser()
    if fallback.is_file():
        return str(fallback)
    return None


def _validate_directory(directory: str) -> str | None:
    """Return error message if directory is invalid, else None."""
    if not Path(directory).is_absolute():
        return "directory must be an absolute path"
    if not Path(directory).exists():
        return f"Directory does not exist: {directory}"
    return None


@mcp.tool()
def run(
    directory: str,
    message: str,
    permission_mode: Optional[str] = "bypassPermissions",
) -> str:
    """Run a message in a Claude Code session for the given directory.

    Auto-creates a new session on first call; auto-resumes on subsequent calls.
    Sessions persist across agent runs, keyed by absolute directory path.

    WARNING: The default permission_mode ('bypassPermissions') allows Claude
    Code to edit files and run shell commands without prompting. Only use in
    trusted, sandboxed directories.

    Args:
        directory: Absolute path to the working directory for the Claude Code session.
        message: The task or message to send to Claude Code.
        permission_mode: One of: acceptEdits, bypassPermissions (default),
            default, dontAsk, plan, auto.
    """
    dir_error = _validate_directory(directory)
    if dir_error:
        return json.dumps({"error": dir_error})

    mode = permission_mode or "bypassPermissions"
    if mode not in ALLOWED_PERMISSION_MODES:
        allowed = ", ".join(sorted(ALLOWED_PERMISSION_MODES))
        return json.dumps({"error": f"Invalid permission_mode '{mode}'. Allowed: {allowed}"})

    claude_bin = _find_claude()
    if not claude_bin:
        return json.dumps({"error": "claude CLI not found. Install Claude Code first."})

    return _run_session(directory, message, mode, claude_bin, session_reset=False)


def _run_session(
    directory: str,
    message: str,
    mode: str,
    claude_bin: str,
    session_reset: bool,
) -> str:
    """Execute the claude subprocess, handling stale session retry."""
    session_id = sessions.get_session(directory)

    cmd = [claude_bin, "-p", message, "--output-format", "json", "--permission-mode", mode]
    if session_id:
        cmd += ["--resume", session_id]

    try:
        proc = subprocess.run(
            cmd,
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "claude_code__run timed out after 600s"})

    # Stale session: non-zero exit when we tried to resume → clear and retry once
    if proc.returncode != 0 and session_id:
        sessions.clear_session(directory)
        return _run_session(directory, message, mode, claude_bin, session_reset=True)

    if proc.returncode != 0:
        return json.dumps({
            "error": f"claude exited with code {proc.returncode}",
            "stderr": proc.stderr[:2000],
        })

    # Parse JSON output from claude
    raw = proc.stdout
    new_session_id: str | None = None
    try:
        data = json.loads(raw)
        output = data.get("result", raw)
        new_session_id = data.get("session_id")
    except (json.JSONDecodeError, ValueError):
        output = raw

    # Persist new session ID; fall back to existing if claude didn't return one
    if new_session_id:
        sessions.save_session(directory, new_session_id)
    elif session_id and not session_reset:
        new_session_id = session_id

    # Truncate output
    if isinstance(output, str) and len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n\n[Output truncated]"

    result: dict = {
        "directory": directory,
        "output": output,
        "session_id": new_session_id,
        "session_reset": session_reset,
    }

    if new_session_id is None and not session_reset:
        result["parse_warning"] = "Could not parse claude output as JSON"

    return json.dumps(result)


@mcp.tool()
def reset(directory: str) -> str:
    """Clear the persisted Claude Code session for a directory.

    The next claude_code__run call on this directory will start a fresh session.

    Args:
        directory: Absolute path to the working directory whose session to clear.
    """
    if not Path(directory).is_absolute():
        return json.dumps({"error": "directory must be an absolute path"})

    existed = sessions.clear_session(directory)
    status = "reset" if existed else "not_found"
    return json.dumps({"status": status, "directory": directory})


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run validation and reset tests**

```bash
uv run pytest tests/test_claude_code_tool.py -v -k "run_rejects or reset"
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add ezagent/tools/builtins/claude_code/main.py tests/test_claude_code_tool.py
git commit -m "feat: add claude_code main.py with validation and reset tool"
```

---

## Task 3: Subprocess Execution Tests (`run` tool with mocked `claude`)

**Files:**
- Modify: `tests/test_claude_code_tool.py`

### Background

Test the `run` tool's subprocess logic using `unittest.mock.patch`. No actual `claude` binary needed. The mocks replace `subprocess.run` and `shutil.which`.

- [ ] **Step 1: Add subprocess mock tests**

Append to `tests/test_claude_code_tool.py`:

```python
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
    # Also patch the fallback path check so it returns False
    # (patching Path.is_file only for the fallback ~/.local/bin/claude check,
    # not for Path.exists which is used by _validate_directory)
    d = tmp_path / "repo"
    d.mkdir()
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
```

- [ ] **Step 2: Run all unit tests**

```bash
uv run pytest tests/test_claude_code_tool.py -v
```

Expected: all tests pass (the implementation from Task 2 already handles these cases).

- [ ] **Step 3: Commit**

```bash
git add tests/test_claude_code_tool.py
git commit -m "test: add subprocess mock tests for claude_code run tool"
```

---

## Task 4: Register Tool + Update README

**Files:**
- Modify: `ezagent/tools/builtins/__init__.py`
- Modify: `README.md`

- [ ] **Step 1: Add `claude_code` to `PREBUILT_TOOLS`**

In `ezagent/tools/builtins/__init__.py`, add one line to `PREBUILT_TOOLS`:

```python
PREBUILT_TOOLS = {
    "memory": _BUILTINS_DIR / "memory",
    "sqlite": _BUILTINS_DIR / "sqlite",
    "web_search": _BUILTINS_DIR / "web_search",
    "http": _BUILTINS_DIR / "http",
    "filesystem": _BUILTINS_DIR / "filesystem",
    "arxiv": _BUILTINS_DIR / "arxiv",
    "pdf_reader": _BUILTINS_DIR / "pdf_reader",
    "perplexity_research": _BUILTINS_DIR / "perplexity_research",
    "extract_structured": _BUILTINS_DIR / "extract_structured",
    "claude_code": _BUILTINS_DIR / "claude_code",   # ← add this line
}
```

- [ ] **Step 2: Add row to README prebuilt tools table**

In `README.md`, find the prebuilt tools table (around line 117) and add a row at the end of the table:

```markdown
| `claude_code`         | Spawn and drive multi-turn Claude Code sessions for long-running coding tasks — requires `claude` CLI installed (`claude --version` to verify) |
```

- [ ] **Step 3: Verify all existing tests still pass**

```bash
uv run pytest tests/ -x -q
```

Expected: all pass, no regressions.

- [ ] **Step 4: Commit**

```bash
git add ezagent/tools/builtins/__init__.py README.md
git commit -m "feat: register claude_code prebuilt tool and update README"
```

---

## Task 5: Integration Tests (claude CLI present)

**Files:**
- Modify: `tests/test_claude_code_tool.py`

### Background

These tests run against the real `claude` binary and are automatically skipped when it is absent. They verify the full subprocess + session persistence flow end-to-end, using a trivial prompt that completes quickly.

- [ ] **Step 1: Add integration tests**

Append to `tests/test_claude_code_tool.py`:

```python
# ---------------------------------------------------------------------------
# Integration tests — skipped if claude CLI not available
# ---------------------------------------------------------------------------

_CLAUDE_AVAILABLE = bool(
    shutil.which("claude") or Path("~/.local/bin/claude").expanduser().is_file()
)
skip_no_claude = pytest.mark.skipif(
    not _CLAUDE_AVAILABLE,
    reason="claude CLI not installed — skipping integration tests",
)


@skip_no_claude
def test_integration_run_creates_session(tmp_path):
    """Full round-trip: run creates a session and persists it."""
    from ezagent.tools.builtins.claude_code.sessions import get_session
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool(
        "run",
        directory=str(d),
        message='Reply with the single word "DONE" and nothing else.',
    )
    assert "error" not in result, f"Unexpected error: {result}"
    assert result["session_id"] is not None
    assert get_session(str(d)) == result["session_id"]
    assert result["session_reset"] is False


@skip_no_claude
def test_integration_run_resumes_session(tmp_path):
    """Second run does not trigger session_reset."""
    d = tmp_path / "repo"
    d.mkdir()
    first = _call_tool(
        "run",
        directory=str(d),
        message='Reply with the single word "FIRST" and nothing else.',
    )
    assert "error" not in first

    second = _call_tool(
        "run",
        directory=str(d),
        message='Reply with the single word "SECOND" and nothing else.',
    )
    assert "error" not in second
    # Session resume worked: no context reset
    assert second["session_reset"] is False


@skip_no_claude
def test_integration_reset(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    _call_tool("run", directory=str(d), message='Reply "DONE".')
    result = _call_tool("reset", directory=str(d))
    assert result["status"] == "reset"

    from ezagent.tools.builtins.claude_code.sessions import get_session
    assert get_session(str(d)) is None


@skip_no_claude
def test_integration_reset_not_found(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    result = _call_tool("reset", directory=str(d))
    assert result["status"] == "not_found"


@skip_no_claude
def test_integration_parallel_calls_different_directories(tmp_path):
    """Parallel agents writing to different directories do not corrupt sessions.json."""
    import concurrent.futures
    from ezagent.tools.builtins.claude_code.sessions import get_session

    dirs = [tmp_path / f"repo-{i}" for i in range(4)]
    for d in dirs:
        d.mkdir()

    def run_in_dir(d):
        return _call_tool(
            "run",
            directory=str(d),
            message='Reply with the single word "DONE" and nothing else.',
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(run_in_dir, d): d for d in dirs}
        results = {d: f.result() for f, d in [(f, futures[f]) for f in concurrent.futures.as_completed(futures)]}

    for d, result in results.items():
        assert "error" not in result, f"Error for {d}: {result}"
        session_id = result["session_id"]
        assert session_id is not None
        # Each directory has its own independently persisted session
        assert get_session(str(d)) == session_id
```

- [ ] **Step 2: Run all tests**

```bash
uv run pytest tests/test_claude_code_tool.py -v
```

Expected: unit tests pass; integration tests pass or show `SKIPPED` if `claude` absent.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/ -x -q
```

Expected: all existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_claude_code_tool.py
git commit -m "test: add integration tests for claude_code tool (skipped if claude absent)"
```

---

## Task 6: Smoke Test with `ez init`

**Goal:** Verify the tool loads correctly in a real ezagent project scaffold.

- [ ] **Step 1: Scaffold a test project**

```bash
cd /tmp
uv run ez init claude-code-smoke-test
cd claude-code-smoke-test
```

- [ ] **Step 2: Edit `agents.yml`**

Replace `agents.yml` with:

```yaml
provider: anthropic

agents:
  coder:
    tools: claude_code
    description: "An agent that can run Claude Code sessions in a directory"
```

- [ ] **Step 3: Start daemon and verify tool is visible**

```bash
uv run ez start &
sleep 2
uv run ez run coder "List the tools you have available."
uv run ez stop
```

Expected: response mentions `claude_code__run` and `claude_code__reset`.

- [ ] **Step 4: Clean up**

```bash
cd /Users/sarveshbhatnagar/Development/ezagent
rm -rf /tmp/claude-code-smoke-test
```

- [ ] **Step 5: Final commit**

```bash
git add -p
git commit -m "feat: claude_code prebuilt tool — complete"
```

---

## Done

The `claude_code` prebuilt tool is ready. Agents use it in `agents.yml`:

```yaml
agents:
  coding_agent:
    tools: claude_code
    description: "Senior engineer that implements features using Claude Code sessions"
```

Agents call `claude_code__run(directory, message)` for coding tasks and `claude_code__reset(directory)` when done.
