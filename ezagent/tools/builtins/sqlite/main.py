"""Prebuilt SQLite tool for ezagent.

Provides deterministic key-value storage using SQLite. Use this for
structured, reproducible state (e.g. preferences, caches, exact lookups)
instead of semantic vector memory when you need deterministic behavior.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastmcp import FastMCP

mcp = FastMCP("sqlite")

TABLE_NAME = "kv"


def _get_db_path() -> Path:
    project_dir = os.environ.get("EZAGENT_PROJECT_DIR", ".")
    db_dir = Path(project_dir) / ".ezagent" / "sqlite"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "store.db"


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Implementation (for testing and tool wrappers)
# ---------------------------------------------------------------------------


def _sqlite_store_impl(key: str, value: str) -> str:
    try:
        from datetime import datetime, timezone

        db_path = _get_db_path()
        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            f"INSERT INTO {TABLE_NAME} (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?",
            (key, value, now, value, now),
        )
        conn.commit()
        conn.close()
        return json.dumps({"status": "stored", "key": key})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _sqlite_get_impl(key: str) -> str:
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        row = conn.execute(
            f"SELECT value FROM {TABLE_NAME} WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
        if row is None:
            return json.dumps({"found": False})
        return json.dumps({"found": True, "value": row[0]})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _sqlite_delete_impl(key: str) -> str:
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        conn.execute(f"DELETE FROM {TABLE_NAME} WHERE key = ?", (key,))
        conn.commit()
        conn.close()
        return json.dumps({"status": "deleted", "key": key})
    except Exception as e:
        return json.dumps({"error": str(e)})


def _sqlite_list_impl(prefix: str | None = None) -> str:
    try:
        db_path = _get_db_path()
        conn = sqlite3.connect(str(db_path))
        _ensure_schema(conn)
        if prefix:
            rows = conn.execute(
                f"SELECT key FROM {TABLE_NAME} WHERE key LIKE ? ORDER BY key",
                (prefix + "%",),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT key FROM {TABLE_NAME} ORDER BY key"
            ).fetchall()
        conn.close()
        keys = [r[0] for r in rows]
        return json.dumps({"keys": keys, "count": len(keys)})
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def sqlite_store(key: str, value: str) -> str:
    """Store a value by key (overwrites if key exists).

    Deterministic: same key always maps to the last stored value.
    Use for preferences, caches, or any exact key-value state.

    Args:
        key: Unique key (e.g. "user:alice", "config:theme").
        value: String value to store.
    """
    return _sqlite_store_impl(key, value)


@mcp.tool()
def sqlite_get(key: str) -> str:
    """Get a value by key.

    Returns found=true and the value if the key exists, otherwise found=false.

    Args:
        key: The key to look up.
    """
    return _sqlite_get_impl(key)


@mcp.tool()
def sqlite_delete(key: str) -> str:
    """Delete a key and its value.

    Args:
        key: The key to delete.
    """
    return _sqlite_delete_impl(key)


@mcp.tool()
def sqlite_list(prefix: str | None = None) -> str:
    """List stored keys, optionally filtered by prefix.

    Args:
        prefix: If given, only return keys that start with this string (e.g. "user:").
    """
    return _sqlite_list_impl(prefix)


if __name__ == "__main__":
    mcp.run()
