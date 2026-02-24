"""Tests for tool management and MCP client handling."""

import tempfile
from pathlib import Path

import pytest


class TestToolManagerLifecycle:
    """Test tool manager initialization and cleanup."""

    @pytest.mark.asyncio
    async def test_disconnect_should_check_client_exists(self):
        """
        Verify that disconnect handles None clients gracefully.
        
        If a client is None or already disconnected, disconnect should
        not raise exceptions.
        """
        from ezagent.tools.manager import ToolManager

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "tools").mkdir()

            manager = ToolManager(
                project_dir=project_dir,
                tool_names=[],
                agent_names=[],
            )

            # Manually add a None client to simulate corruption
            manager._clients["broken_client"] = None

            # This should not raise an exception
            await manager.disconnect()
