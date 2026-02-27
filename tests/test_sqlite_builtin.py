"""Tests for the builtin SQLite tool (deterministic key-value store)."""

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def sqlite_tool_env(tmp_path):
    """Set EZAGENT_PROJECT_DIR so the tool uses a temp DB."""
    env = os.environ.copy()
    env["EZAGENT_PROJECT_DIR"] = str(tmp_path)
    return env


def test_sqlite_store_and_get(sqlite_tool_env):
    """Store a value and retrieve it by key (deterministic)."""
    from ezagent.tools.builtins.sqlite.main import _sqlite_get_impl, _sqlite_store_impl

    orig_os_environ = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        out = _sqlite_store_impl(key="user:alice", value="preference=dark")
        data = json.loads(out)
        assert data.get("status") == "stored"
        assert data.get("key") == "user:alice"

        out2 = _sqlite_get_impl(key="user:alice")
        data2 = json.loads(out2)
        assert data2.get("found") is True
        assert data2.get("value") == "preference=dark"
    finally:
        os.environ.clear()
        os.environ.update(orig_os_environ)


def test_sqlite_get_missing_returns_not_found(sqlite_tool_env):
    """Get for missing key returns found=false."""
    from ezagent.tools.builtins.sqlite.main import _sqlite_get_impl

    orig = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        out = _sqlite_get_impl(key="nonexistent")
        data = json.loads(out)
        assert data.get("found") is False
        assert "value" not in data or data.get("value") is None
    finally:
        os.environ.clear()
        os.environ.update(orig)


def test_sqlite_delete(sqlite_tool_env):
    """Delete removes the key; get afterwards returns not found."""
    from ezagent.tools.builtins.sqlite.main import (
        _sqlite_delete_impl,
        _sqlite_get_impl,
        _sqlite_store_impl,
    )

    orig = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        _sqlite_store_impl(key="to_delete", value="x")
        out = _sqlite_delete_impl(key="to_delete")
        data = json.loads(out)
        assert data.get("status") == "deleted"
        out2 = _sqlite_get_impl(key="to_delete")
        assert json.loads(out2).get("found") is False
    finally:
        os.environ.clear()
        os.environ.update(orig)


def test_sqlite_list_keys(sqlite_tool_env):
    """List returns stored keys; prefix filters."""
    from ezagent.tools.builtins.sqlite.main import _sqlite_list_impl, _sqlite_store_impl

    orig = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        _sqlite_store_impl(key="user:a", value="1")
        _sqlite_store_impl(key="user:b", value="2")
        _sqlite_store_impl(key="config:x", value="3")
        out = _sqlite_list_impl()
        data = json.loads(out)
        keys = data.get("keys", [])
        assert set(keys) == {"user:a", "user:b", "config:x"}

        out2 = _sqlite_list_impl(prefix="user:")
        data2 = json.loads(out2)
        assert set(data2.get("keys", [])) == {"user:a", "user:b"}
    finally:
        os.environ.clear()
        os.environ.update(orig)


def test_sqlite_store_overwrites(sqlite_tool_env):
    """Storing same key again overwrites (deterministic)."""
    from ezagent.tools.builtins.sqlite.main import _sqlite_get_impl, _sqlite_store_impl

    orig = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        _sqlite_store_impl(key="k", value="v1")
        _sqlite_store_impl(key="k", value="v2")
        out = _sqlite_get_impl(key="k")
        assert json.loads(out).get("value") == "v2"
    finally:
        os.environ.clear()
        os.environ.update(orig)


def test_sqlite_uses_project_dir(sqlite_tool_env, tmp_path):
    """DB file is created under .ezagent/sqlite in project dir."""
    from ezagent.tools.builtins.sqlite.main import _sqlite_store_impl

    orig = os.environ.copy()
    try:
        os.environ.clear()
        os.environ.update(sqlite_tool_env)
        _sqlite_store_impl(key="x", value="y")
        db_path = tmp_path / ".ezagent" / "sqlite" / "store.db"
        assert db_path.exists()
        assert db_path.suffix == ".db"
    finally:
        os.environ.clear()
        os.environ.update(orig)
