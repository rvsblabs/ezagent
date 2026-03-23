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
#
# sys.path.insert + bare `import sessions` ensures this works both in the
# production subprocess (where only the tool directory is on the path) and in
# tests (where _call_tool re-registers the patched sessions module under the
# bare "sessions" key before reimporting main, so monkeypatches are preserved).
sys.path.insert(0, str(Path(__file__).parent))
import sessions  # noqa: E402

from fastmcp import FastMCP
from fastmcp.tools.tool import FunctionTool

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

    # On the retry path (session_reset=True) there should be no session — the
    # caller cleared it before recursing.  If one somehow reappears (e.g. a race),
    # clear it defensively so we never recurse a third time.
    if session_reset and session_id:
        sessions.clear_session(directory)
        session_id = None

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


# Register tools with FastMCP without replacing the module-level callables.
# Using FunctionTool.from_function + mcp.add_tool keeps `run` and `reset`
# as plain Python functions (callable in tests) while still exposing them
# as MCP tools when the server runs.
mcp.add_tool(FunctionTool.from_function(run))
mcp.add_tool(FunctionTool.from_function(reset))

if __name__ == "__main__":
    mcp.run()
