# Claude Code Tool — Design Spec

**Date:** 2026-03-23
**Status:** Approved
**Feature:** `claude_code` prebuilt tool for ezagent

---

## Overview

Add a new prebuilt tool `claude_code` that allows ezagent agents to spawn and interact with Claude Code (the `claude` CLI) for long-running, multi-turn coding sessions. Agents can assign coding tasks to a Claude Code session rooted at a specific directory, iterate on results, and resume sessions across multiple agent runs.

---

## Goals

- Agents can send messages to a Claude Code session in a specific directory and get back the output.
- Sessions persist across agent runs (resumable by directory path).
- Session management is transparent to the agent's LLM — no session ID tracking required.
- Permission mode defaults to `bypassPermissions`, configurable per call.
- Parallel agents each work in their own directory, naturally isolated.

---

## Non-Goals (v1)

- Multiple concurrent sessions per directory.
- Named sessions.
- Streaming output (fire-and-wait model only).
- Output parsing/structuring beyond raw text.
- Concurrent calls from multiple agents to the **same** directory: unsupported. If two parallel agents are assigned the same directory, both will attempt `--resume` on the same session ID; only one will succeed, and the other will trigger the stale-session retry (starting a fresh session). This produces confusing, non-deterministic results. Orchestration planners must assign distinct directories to parallel workers.

---

## Architecture

### Location

```
ezagent/tools/builtins/claude_code/
  main.py          # FastMCP server — exposes 2 tools
  sessions.py      # Session registry: load/save/lookup by directory
  requirements.txt # filelock dependency for concurrent write safety
```

No `__init__.py` — consistent with all other prebuilt tool directories which are located by path, not Python import.

### Registration

Add to `PREBUILT_TOOLS` in `ezagent/tools/builtins/__init__.py`:

```python
"claude_code": _BUILTINS_DIR / "claude_code",
```

Also add a row to the prebuilt tools table in `README.md`:

| `claude_code` | `claude_code__run`, `claude_code__reset` | — (requires `claude` CLI installed) |

---

## Tool Naming

ezagent's `ToolManager` namespaces tool function names as `{tool_dir_name}__{function_name}`. With the tool directory named `claude_code`, FastMCP functions should be named `run` and `reset` — agents will see them as:

- `claude_code__run`
- `claude_code__reset`

---

## Tools Exposed to Agents

### `claude_code__run`

Run a message in a Claude Code session for a given directory. Auto-creates a new session on first call; auto-resumes on subsequent calls.

**Parameters:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `directory` | `str` | yes | — | Absolute path to the working directory |
| `message` | `str` | yes | — | The task or message to send to Claude Code |
| `permission_mode` | `str` | no | `bypassPermissions` | One of: `acceptEdits`, `bypassPermissions`, `default`, `dontAsk`, `plan`, `auto` |

**Important:** `bypassPermissions` allows Claude Code to edit files, run bash commands, and perform any filesystem operations without prompting. The tool docstring must warn agents of this. Only use in trusted, sandboxed directories.

**Validation (before spawning subprocess):**
1. `directory` must be an absolute path (`Path(directory).is_absolute()`). Relative paths are rejected.
2. `directory` must exist on disk.
3. `permission_mode` must be one of the allowed values listed above.

**Returns (JSON string):**
```json
{
  "directory": "/abs/path/to/repo",
  "output": "Claude Code's full text response...",
  "session_id": "uuid-of-session",
  "session_reset": false
}
```

`session_reset: true` is set when a stale session was detected and cleared — the agent receives a response but should be aware prior context was lost.

Output is truncated to `MAX_OUTPUT_CHARS = 50_000` characters, consistent with other prebuilt tools.

**Execution flow:**
1. Validate inputs (directory absolute + exists, permission_mode allowed).
2. Resolve `claude` binary: `shutil.which("claude")` first, then check `~/.local/bin/claude` as fallback. Error if neither found.
3. Load session state file; look up `directory`.
4. Build subprocess command:
   ```
   claude -p "<message>"
          --output-format json
          --permission-mode <permission_mode>
          [--resume <session_id>]   # only if session exists for this directory
   ```
   Run with `cwd=directory`, `timeout=600`.
5. Parse JSON response; extract `result` (output text) and `session_id`.
   - If JSON parse fails: use raw stdout as `output`, set `session_id: null`, add `"parse_warning"` field.
6. Save `session_id` for `directory` in state file.
7. Truncate `output` to `MAX_OUTPUT_CHARS`.
8. Return structured JSON.

**Stale session handling:** If `--resume <session_id>` fails (non-zero exit or JSON error indicating unknown session), clear the stale entry from the state file, retry once as a new session, and set `session_reset: true` in the response. If the retry also fails, the stale entry remains cleared (so subsequent calls do not re-attempt the dead session) and the error is surfaced as `{"error": "...", "stderr": "..."}` without a second retry.

**Blocking note:** `subprocess.run(..., timeout=600)` is a blocking call. This is safe because `claude_code` has a `requirements.txt`, so the daemon connects to it via `UvStdioTransport` in its own dedicated subprocess. Blocking for up to 600s only blocks that MCP subprocess, not the daemon or other tools.

---

### `claude_code__reset`

Clear the persisted session for a directory. The next `claude_code__run` call on that directory starts a fresh session.

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `directory` | `str` | yes | Absolute path to the working directory |

**Returns (JSON string):**

If session existed and was cleared:
```json
{"status": "reset", "directory": "/abs/path/to/repo"}
```

If no session existed for that directory:
```json
{"status": "not_found", "directory": "/abs/path/to/repo"}
```

---

## Session State File

**Location:** `~/.ezagent/claude_code_sessions.json`

User-level (not project-level) because sessions are keyed by directory, not by ezagent project. `sessions.py` must create `~/.ezagent/` if it does not exist (`Path.mkdir(parents=True, exist_ok=True)`).

`~/.ezagent/` is the designated user-global state area for ezagent data that spans multiple projects.

**Format:**
```json
{
  "/abs/path/to/repo": "uuid-session-id",
  "/abs/path/to/other-repo": "uuid-session-id-2"
}
```

**Concurrency:** `sessions.py` uses `filelock` to serialize reads/writes, preventing corruption when multiple parallel agents write concurrently.

---

## Data Flow

```
Agent LLM
  → calls claude_code__run(directory, message, permission_mode)
    → validate inputs (absolute path, exists, valid mode)
    → resolve claude binary (shutil.which → ~/.local/bin/claude fallback)
    → load sessions.json (with file lock)
    → lookup directory → session_id (or None)
    → build claude CLI command
    → subprocess.run(cmd, cwd=directory, capture_output=True, timeout=600)
    → parse JSON stdout → extract result text + session_id
    → save session_id to sessions.json (with file lock)
    → truncate output to MAX_OUTPUT_CHARS
    → return {"directory": ..., "output": ..., "session_id": ..., "session_reset": false}
  → LLM reads output, decides next action
  → repeat as needed
  → calls claude_code__reset(directory) when session no longer needed
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| `claude` not in PATH or `~/.local/bin/` | `{"error": "claude CLI not found. Install Claude Code first."}` |
| `directory` is a relative path | `{"error": "directory must be an absolute path"}` |
| `directory` does not exist | `{"error": "Directory does not exist: <path>"}` |
| Invalid `permission_mode` | `{"error": "Invalid permission_mode '...'. Allowed: acceptEdits, bypassPermissions, default, dontAsk, plan, auto"}` |
| Subprocess non-zero exit | `{"error": "claude exited with code N", "stderr": "..."}` |
| JSON parse failure from claude | `{"output": "<raw stdout, truncated>", "session_id": null, "parse_warning": "Could not parse claude output as JSON"}` |
| Stale session ID (resume fails) | Retry as new session, `"session_reset": true` in response; error if retry fails |
| State file I/O error | Log warning, continue without session persistence; degrade gracefully |
| Subprocess timeout (>600s) | Kill process, return `{"error": "claude_code__run timed out after 600s"}` |

---

## Permission Modes

Default: `bypassPermissions`

Valid values (matching `claude --permission-mode` choices):
- `acceptEdits` — auto-accept file edits, prompt for other actions
- `bypassPermissions` — bypass all permission prompts (default)
- `default` — standard interactive permission handling
- `dontAsk` — never ask for permission
- `plan` — plan mode (no writes, only propose changes)
- `auto` — automatic mode

Note: `bypassPermissions` is distinct from the CLI's `--dangerously-skip-permissions` boolean flag. The `--permission-mode` option is used here, not the flag.

---

## Testing

**File:** `tests/test_claude_code_tool.py`

### Unit tests (no `claude` CLI required)

- `sessions.py`: load/save/lookup/reset, `not_found` on unknown directory, concurrent write safety (threaded test)
- Input validation: relative path rejected, non-existent directory, invalid `permission_mode`
- JSON parse failure fallback path (mock subprocess returning non-JSON)
- Stale session retry logic (mock subprocess: first call fails with non-zero exit, second succeeds)
- Output truncation at `MAX_OUTPUT_CHARS`

### Integration tests (skipped if `claude` CLI not available)

Follow the CI env contract pattern in `tests/ci_integration_env_contract.py`. Use a `CLAUDE_CODE_AVAILABLE` guard or `shutil.which("claude") is None` skip condition, consistent with how other integration tests gate on external deps.

- `claude_code__run` on a temp directory: verify session ID captured and persisted in state file
- Second call to same directory: verify `--resume` flag is used (mock or check subprocess args)
- `claude_code__reset`: verify state file entry is cleared, returns `"reset"`
- `claude_code__reset` on unknown directory: returns `"not_found"`
- Parallel calls to different directories: verify no state file corruption (concurrent threads)

---

## `agents.yml` Usage Example

```yaml
agents:
  coding_agent:
    tools: claude_code
    description: "Senior engineer that implements features and fixes bugs using Claude Code sessions"
```

**Example agent interaction:**
```
User → coding_agent: "Fix the authentication bug in /home/user/myapp"

coding_agent → claude_code__run("/home/user/myapp", "Investigate and fix the auth bug in src/auth.py. Run the tests after.")
  ← {"output": "I found the issue in auth.py line 42... Fixed and tests pass.", "session_id": "abc-123", "session_reset": false}

coding_agent → claude_code__run("/home/user/myapp", "Also update the docs in README.md to reflect the change.")
  ← {"output": "Updated README.md with auth flow description.", "session_id": "abc-123", "session_reset": false}

coding_agent → claude_code__reset("/home/user/myapp")
  ← {"status": "reset", "directory": "/home/user/myapp"}
```

---

## Parallel Usage

Multiple agents in an orchestration each working on different repos:

```yaml
orchestrations:
  multi_repo_fixer:
    pattern: plan_and_delegate
    planner: planner_agent
    workers: [coding_agent_1, coding_agent_2]
    aggregator: summary_agent
    parallel: true
```

Each worker calls `claude_code__run` with its own directory → different session IDs → no shared state. File locking in `sessions.py` ensures `~/.ezagent/claude_code_sessions.json` is written safely under concurrent access.
