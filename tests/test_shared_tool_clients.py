"""Tests for shared prebuilt tool client behavior.

Verifies that ToolManager reuses shared clients instead of spawning new
subprocesses, and that the daemon wires shared_clients correctly to agents.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ezagent.tools.manager import ToolManager
from ezagent.tools.builtins import PREBUILT_TOOLS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(tool_names: list[str]):
    """Return a mock FastMCP Client that advertises the given tool names."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    mock_tools = []
    for name in tool_names:
        t = MagicMock()
        t.name = name
        t.description = f"mock {name}"
        t.inputSchema = {"type": "object", "properties": {}}
        mock_tools.append(t)

    client.list_tools = AsyncMock(return_value=mock_tools)
    return client


# ---------------------------------------------------------------------------
# ToolManager: shared client is reused, no new subprocess spawned
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shared_client_reused_not_spawned(tmp_path):
    """When a prebuilt tool has a shared client, no new subprocess is started."""
    shared_client = _make_mock_client(["memory_store", "memory_search"])

    tm = ToolManager(
        project_dir=tmp_path,
        tool_names=["memory"],
        agent_names=[],
        shared_clients={"memory": shared_client},
    )

    with patch.object(tm, "_connect_tool_dir", new_callable=AsyncMock) as mock_connect:
        await tm.connect()
        mock_connect.assert_not_called()

    # Schema should be registered from the shared client
    schemas = tm.get_tool_schemas()
    names = {s["name"] for s in schemas}
    assert "memory__memory_store" in names
    assert "memory__memory_search" in names


@pytest.mark.asyncio
async def test_non_shared_prebuilt_spawns_subprocess(tmp_path):
    """Prebuilt tools NOT in shared_clients still spawn their own subprocess."""
    tm = ToolManager(
        project_dir=tmp_path,
        tool_names=["memory"],
        agent_names=[],
        shared_clients={},  # no shared clients
    )

    with patch.object(tm, "_connect_tool_dir", new_callable=AsyncMock) as mock_connect:
        await tm.connect()
        mock_connect.assert_called_once_with(
            "memory", PREBUILT_TOOLS["memory"], env=pytest.approx(mock_connect.call_args[1]["env"])
        )


# ---------------------------------------------------------------------------
# ToolManager: disconnect skips shared clients
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_skips_shared_clients(tmp_path):
    """disconnect() must NOT call __aexit__ on shared clients."""
    shared_client = _make_mock_client(["memory_store"])

    tm = ToolManager(
        project_dir=tmp_path,
        tool_names=["memory"],
        agent_names=[],
        shared_clients={"memory": shared_client},
    )

    with patch.object(tm, "_connect_tool_dir", new_callable=AsyncMock):
        await tm.connect()
        # Manually register the shared client as if connect() did it
        tm._clients["memory"] = shared_client

    await tm.disconnect()

    shared_client.__aexit__.assert_not_called()


@pytest.mark.asyncio
async def test_disconnect_calls_aexit_on_non_shared_clients(tmp_path):
    """disconnect() must call __aexit__ on non-shared (locally spawned) clients."""
    local_client = _make_mock_client(["web_search"])

    tm = ToolManager(
        project_dir=tmp_path,
        tool_names=[],
        agent_names=[],
        shared_clients={},
    )
    # Manually inject a "locally spawned" client
    tm._clients["web_search"] = local_client

    await tm.disconnect()

    local_client.__aexit__.assert_called_once()


# ---------------------------------------------------------------------------
# ToolManager: mixed — one shared, one local
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disconnect_mixed_shared_and_local(tmp_path):
    """Only local (non-shared) clients get disconnected."""
    shared_client = _make_mock_client(["memory_store"])
    local_client = _make_mock_client(["http_request"])

    tm = ToolManager(
        project_dir=tmp_path,
        tool_names=[],
        agent_names=[],
        shared_clients={"memory": shared_client},
    )
    tm._clients["memory"] = shared_client
    tm._clients["http"] = local_client

    await tm.disconnect()

    shared_client.__aexit__.assert_not_called()
    local_client.__aexit__.assert_called_once()


# ---------------------------------------------------------------------------
# AgentDaemon._connect_shared_tools wires clients correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_daemon_connect_shared_tools(tmp_path):
    """_connect_shared_tools() produces one client per unique prebuilt tool."""
    from ezagent.config import AgentConfig, ProjectConfig
    from ezagent.daemon import AgentDaemon

    # Build a minimal config with two agents both using "memory"
    cfg = MagicMock(spec=ProjectConfig)
    cfg.project_dir = tmp_path
    cfg.events_db_path = tmp_path / ".ezagent" / "events.db"
    cfg.provider = "anthropic"
    cfg.model = "claude-haiku-4-5-20251001"
    cfg.discussions = {}

    agent_a = MagicMock(spec=AgentConfig)
    agent_a.tools = ["memory", "web_search"]
    agent_a.skills = []
    agent_a.schedule = []

    agent_b = MagicMock(spec=AgentConfig)
    agent_b.tools = ["memory"]
    agent_b.skills = []
    agent_b.schedule = []

    cfg.agents = {"agent_a": agent_a, "agent_b": agent_b}

    daemon = AgentDaemon(cfg)

    connected_tools = []

    async def fake_connect(self_tm):
        # Record which tool names this ToolManager was asked to connect
        connected_tools.extend(self_tm._prebuilt_tool_names)
        # Fake the clients so the daemon can read _clients
        for name in self_tm._prebuilt_tool_names:
            self_tm._clients[name] = _make_mock_client([])

    with patch.object(ToolManager, "connect", fake_connect):
        await daemon._connect_shared_tools()

    # Should have connected exactly the unique prebuilt tools (sorted)
    assert sorted(connected_tools) == ["memory", "web_search"]
    # shared_tm should hold both clients
    assert set(daemon._shared_tm._clients.keys()) == {"memory", "web_search"}


@pytest.mark.asyncio
async def test_daemon_shared_clients_passed_to_agents(tmp_path):
    """Agents receive the shared clients dict from the daemon."""
    from ezagent.config import AgentConfig, ProjectConfig, ScheduleEntry
    from ezagent.daemon import AgentDaemon
    from ezagent.agent import Agent

    cfg = MagicMock(spec=ProjectConfig)
    cfg.project_dir = tmp_path
    cfg.events_db_path = tmp_path / ".ezagent" / "events.db"
    cfg.provider = "anthropic"
    cfg.model = "claude-haiku-4-5-20251001"
    cfg.socket_path = str(tmp_path / "test.sock")
    cfg.pid_path = str(tmp_path / "test.pid")
    cfg.discussions = {}
    cfg.orchestrations = {}
    cfg.timezone = "UTC"

    agent_cfg = MagicMock(spec=AgentConfig)
    agent_cfg.tools = ["memory"]
    agent_cfg.skills = []
    agent_cfg.schedule = []
    agent_cfg.provider = None
    agent_cfg.model = None
    agent_cfg.description = "test agent"
    agent_cfg.pre_tools = []
    agent_cfg.run_tools = []

    cfg.agents = {"alpha": agent_cfg}

    daemon = AgentDaemon(cfg)

    shared_client = _make_mock_client(["memory_store"])
    received_shared_clients = {}

    original_agent_init = Agent.__init__

    def capturing_agent_init(self, *args, shared_tool_clients=None, **kwargs):
        received_shared_clients.update(shared_tool_clients or {})
        # Don't call real __init__ to avoid side effects
        self.name = kwargs.get("name", "")
        self._tool_manager = None
        self._shared_tool_clients = shared_tool_clients or {}

    async def fake_agent_initialize(self):
        pass

    async def fake_connect_shared(self):
        daemon._shared_tm = MagicMock()
        daemon._shared_tm._clients = {"memory": shared_client}

    with (
        patch.object(AgentDaemon, "_connect_shared_tools", fake_connect_shared),
        patch("ezagent.daemon.EventLogger") as MockLogger,
        patch("ezagent.daemon.resolve_externals", return_value=({}, {}, ["memory"], [])),
        patch("ezagent.daemon.create_provider", return_value=MagicMock()),
        patch.object(Agent, "__init__", capturing_agent_init),
        patch.object(Agent, "initialize", fake_agent_initialize),
    ):
        MockLogger.return_value.setup = MagicMock()
        daemon._event_logger = MockLogger.return_value
        await daemon.initialize()

    assert "memory" in received_shared_clients
    assert received_shared_clients["memory"] is shared_client
