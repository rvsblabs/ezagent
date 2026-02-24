"""Tests for daemon socket handling and lifecycle."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestDaemonSocketHandling:
    """Test daemon socket operations and error handling."""

    @pytest.mark.asyncio
    async def test_error_response_should_close_writer_properly(self):
        """
        Verify that socket writers are properly closed after error responses.
        
        This prevents resource leaks and unclosed connection warnings.
        """
        from ezagent.daemon import AgentDaemon
        from ezagent.config import ProjectConfig, AgentConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "tools").mkdir()
            (project_dir / "skills").mkdir()

            config = ProjectConfig(
                agents={"test_agent": AgentConfig()},
                project_dir=project_dir,
            )

            daemon = AgentDaemon(config)
            
            # Mock the LLM provider to avoid needing API keys
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
                await daemon.initialize()

                # Mock reader and writer
                reader = AsyncMock()
                reader.read = AsyncMock(
                    return_value=json.dumps(
                        {"agent": "nonexistent_agent", "message": "test"}
                    ).encode()
                )

                writer = AsyncMock()
                writer.write = Mock()
                writer.drain = AsyncMock()
                writer.close = Mock()
                writer.wait_closed = AsyncMock()

                # Handle client with unknown agent
                await daemon._handle_client(reader, writer)

                # Verify proper cleanup
                writer.close.assert_called()
                writer.wait_closed.assert_called()

                await daemon.shutdown()


class TestSchedulerTimezoneHandling:
    """Test scheduler timezone consistency."""

    def test_scheduler_should_use_utc_consistently(self):
        """
        Verify that scheduler uses UTC consistently for all time calculations.
        
        Mixing timezone-aware and naive datetimes can cause subtle bugs.
        """
        from ezagent.daemon import AgentDaemon
        from ezagent.config import ProjectConfig, AgentConfig, ScheduleEntry
        from datetime import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "tools").mkdir()
            (project_dir / "skills").mkdir()

            config = ProjectConfig(
                agents={
                    "scheduled_agent": AgentConfig(
                        schedule=[ScheduleEntry(cron="0 0 * * *", message="daily task")]
                    )
                },
                project_dir=project_dir,
            )

            daemon = AgentDaemon(config)
            
            # Build schedule should not raise timezone-related errors
            daemon._build_schedule()
            
            # Verify all next_run times are timezone-aware
            for entry in daemon._schedule_entries:
                next_run = entry["next_run"]
                assert isinstance(next_run, datetime)
                # Should have timezone info
                assert next_run.tzinfo is not None
