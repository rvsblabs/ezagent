"""Prebuilt filesystem tool for ezagent.

Provides basic file system operations so agents can read, write, list,
and create directories.  Uses Python stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("filesystem")

MAX_READ_CHARS = 100_000


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def read_file(path: str) -> str:
    """Read a file and return its contents.

    Args:
        path: Absolute or relative path to the file to read.
    """
    try:
        p = Path(path).expanduser().resolve()
        content = p.read_text(encoding="utf-8", errors="replace")
        if len(content) > MAX_READ_CHARS:
            content = content[:MAX_READ_CHARS] + "\n\n[Content truncated]"
        return json.dumps({"path": str(p), "content": content})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def write_file(path: str, content: str, append: bool = False) -> str:
    """Write (or append) content to a file.

    Creates parent directories automatically if they don't exist.

    Args:
        path: Absolute or relative path to the file to write.
        content: The text content to write.
        append: If true, append to the file instead of overwriting. Defaults to false.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with p.open(mode, encoding="utf-8") as f:
            bytes_written = f.write(content)
        return json.dumps({"path": str(p), "bytes_written": bytes_written})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_directory(path: str) -> str:
    """List contents of a directory.

    Returns immediate children only (no recursion).

    Args:
        path: Absolute or relative path to the directory to list.
    """
    try:
        p = Path(path).expanduser().resolve()
        entries = []
        for child in sorted(p.iterdir()):
            entry: dict = {"name": child.name}
            if child.is_dir():
                entry["type"] = "directory"
            else:
                entry["type"] = "file"
                try:
                    entry["size"] = child.stat().st_size
                except OSError:
                    entry["size"] = 0
            entries.append(entry)
        return json.dumps({"path": str(p), "entries": entries})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def create_directory(path: str) -> str:
    """Create a directory, including any necessary parent directories.

    No error if the directory already exists (mkdir -p semantics).

    Args:
        path: Absolute or relative path to the directory to create.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return json.dumps({"path": str(p), "created": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
