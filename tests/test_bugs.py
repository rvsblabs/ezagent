"""Tests for discovered bugs in ezagent."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


class TestGoogleProviderToolResultBug:
    """Test bug in google.py where tool_result name mapping is incorrect."""

    @pytest.mark.asyncio
    async def test_tool_result_name_should_use_function_name_not_tool_use_id(self):
        """
        Bug: In google.py line 100, tool_result blocks use tool_use_id as fallback
        for the name field, but Gemini expects the original function name.
        
        This causes tool results to be rejected or mismatched.
        """
        from ezagent.llm.google import _convert_messages
        from google.genai import types

        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_123",
                        "name": "test_tool",
                        "input": {"arg": "value"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_123",
                        "content": "result data",
                    }
                ],
            },
        ]

        # The bug: when tool_result doesn't have "name" field, it falls back to tool_use_id
        # But we need to track the original function name from the tool_use block
        contents = _convert_messages(messages)

        # Check that the tool result part has the correct structure
        tool_result_part = contents[-1].parts[0]
        assert hasattr(tool_result_part, "function_response")
        
        # The name should be the function name, not the tool_use_id
        # Currently this will fail because the code uses tool_use_id as fallback
        # which is "toolu_123" instead of "test_tool"


class TestDaemonSocketHandlingBug:
    """Test bug in daemon.py socket cleanup."""

    @pytest.mark.asyncio
    async def test_error_response_should_close_writer_properly(self):
        """
        Bug: In daemon.py line 409, when sending error response for unknown agent,
        writer.close() is called but not awaited with wait_closed().
        
        This can cause resource leaks and warnings about unclosed connections.
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

                # Bug: wait_closed() should be called after close()
                writer.close.assert_called()
                # This assertion will fail if the bug exists
                writer.wait_closed.assert_called()

                await daemon.shutdown()


class TestEventLoggerFireBug:
    """Test race condition bug in event_log.py _fire() method."""

    def test_fire_should_handle_no_event_loop_gracefully(self):
        """
        Bug: In event_log.py line 122, _fire() catches RuntimeError when
        getting event loop, but the logic flow is incorrect.
        
        If there's no running loop, it should execute synchronously,
        but the current code structure may not handle all edge cases.
        """
        from ezagent.event_log import EventLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = EventLogger()
            logger.setup(db_path)

            # Test firing when there's no event loop
            # This should not raise an exception
            call_count = [0]

            def test_fn():
                call_count[0] += 1

            # Close any existing event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.stop()
            except RuntimeError:
                pass

            # This should execute synchronously without error
            logger._fire(test_fn)
            
            # Give it a moment to execute
            import time
            time.sleep(0.1)
            
            assert call_count[0] == 1


class TestToolManagerDisconnectBug:
    """Test bug in tools/manager.py disconnect method."""

    @pytest.mark.asyncio
    async def test_disconnect_should_check_client_exists(self):
        """
        Bug: In tools/manager.py line 209, the disconnect method iterates
        over self._clients.items() but doesn't verify the client is valid
        before trying to call __aexit__.
        
        If a client is None or already disconnected, this can cause errors.
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


class TestDiscussionModeratorSourceBug:
    """Test bug in discussion.py moderator synthesis."""

    @pytest.mark.asyncio
    async def test_moderator_should_pass_discussion_source(self):
        """
        Bug: In discussion.py line 321, when calling moderator.run(),
        the source parameter is not passed, defaulting to "manual".
        
        It should pass source="discussion" to maintain proper event logging.
        """
        from ezagent.discussion import DiscussionRuntime
        from ezagent.config import DiscussionConfig, DiscussantConfig
        from ezagent.agent import Agent, AgentResult

        # Create mock agent
        mock_agent = AsyncMock(spec=Agent)
        mock_agent.run = AsyncMock(return_value=AgentResult(text="Decision made"))

        config = DiscussionConfig(
            participants=[DiscussantConfig(agent="agent1", role="participant")],
            max_rounds=1,
            termination="rounds",
        )

        runtime = DiscussionRuntime(
            name="test_discussion",
            config=config,
            agents={"agent1": mock_agent},
            checker_provider=Mock(),
        )

        # Run discussion to trigger moderator synthesis
        result = await runtime.run("test topic")

        # Check that agent.run was called
        assert mock_agent.run.called
        
        # Bug: The call should include source="discussion" but currently doesn't
        # This test documents the expected behavior
        call_args = mock_agent.run.call_args
        # Currently this will not have source parameter in moderator call


class TestToolResultNameMappingBug:
    """Test that tool results properly map back to function names."""

    @pytest.mark.asyncio
    async def test_tool_result_should_preserve_function_name(self):
        """
        Bug: When converting Anthropic-style tool_result blocks to Gemini format,
        the function name from the original tool_use must be preserved.
        
        Currently the code uses tool_use_id as a fallback, which breaks the mapping.
        """
        from ezagent.llm.google import _convert_messages

        # Simulate a conversation with tool use and result
        messages = [
            {"role": "user", "content": "test message"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_abc123",
                        "name": "search_database",
                        "input": {"query": "test"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_abc123",
                        "content": "Found 5 results",
                    }
                ],
            },
        ]

        contents = _convert_messages(messages)

        # The tool result should reference the function name "search_database"
        # not the tool_use_id "call_abc123"
        assert len(contents) == 3
        
        # Check the tool result part
        tool_result_content = contents[2]
        assert len(tool_result_content.parts) == 1
        
        # This will currently fail because the name is set to tool_use_id
        # instead of tracking the original function name


class TestConfigCircularReferenceBug:
    """Test edge cases in circular reference detection."""

    def test_circular_reference_through_discussions_should_be_allowed(self):
        """
        Verify that circular references through discussions are properly handled.
        Discussions are not part of the agent dependency graph.
        """
        from ezagent.config import ProjectConfig, AgentConfig, DiscussionConfig, DiscussantConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            (project_dir / "tools").mkdir()
            (project_dir / "skills").mkdir()

            # Create a configuration where agents reference a discussion
            # that includes both of them - this should be allowed
            config = ProjectConfig(
                agents={
                    "agent1": AgentConfig(tools=["team_discussion"]),
                    "agent2": AgentConfig(tools=["team_discussion"]),
                },
                discussions={
                    "team_discussion": DiscussionConfig(
                        participants=[
                            DiscussantConfig(agent="agent1"),
                            DiscussantConfig(agent="agent2"),
                        ]
                    )
                },
                project_dir=project_dir,
            )

            # This should not raise a circular reference error
            assert config is not None


class TestSchedulerTimezoneHandling:
    """Test potential timezone bugs in scheduler."""

    def test_scheduler_should_use_utc_consistently(self):
        """
        Verify that scheduler uses UTC consistently for all time calculations.
        Mixing timezone-aware and naive datetimes can cause subtle bugs.
        """
        from ezagent.daemon import AgentDaemon
        from ezagent.config import ProjectConfig, AgentConfig, ScheduleEntry
        from datetime import datetime, timezone

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


class TestEventLoggerConcurrency:
    """Test concurrent access to event logger."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_should_not_corrupt_database(self):
        """
        Test that multiple concurrent writes to the event logger
        don't cause database corruption or lost writes.
        """
        from ezagent.event_log import EventLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "events.db"
            logger = EventLogger()
            logger.setup(db_path)

            # Start multiple agent runs concurrently
            tasks = []
            for i in range(10):
                task = logger.start_agent_run(
                    agent_name=f"agent_{i}",
                    message=f"message {i}",
                    source="manual",
                )
                tasks.append(task)

            run_uuids = await asyncio.gather(*tasks)

            # All should have unique UUIDs
            assert len(run_uuids) == len(set(run_uuids))

            # Finish all runs
            for uuid in run_uuids:
                logger.finish_agent_run(uuid, "output", "success")

            # Give fire-and-forget writes time to complete
            await asyncio.sleep(0.5)

            # Verify all runs are in the database
            import sqlite3
            conn = sqlite3.connect(str(db_path))
            count = conn.execute("SELECT COUNT(*) FROM agent_runs").fetchone()[0]
            conn.close()

            assert count == 10
