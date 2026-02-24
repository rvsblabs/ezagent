"""Tests for event logging and persistence."""

import asyncio
import tempfile
from pathlib import Path

import pytest


class TestEventLoggerEdgeCases:
    """Test event logger edge cases and error handling."""

    def test_fire_should_handle_no_event_loop_gracefully(self):
        """
        Verify that _fire() handles missing event loop gracefully.
        
        When there's no running event loop, the method should execute
        synchronously without raising exceptions.
        """
        from ezagent.event_log import EventLogger

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            logger = EventLogger()
            logger.setup(db_path)

            # Test firing when there's no event loop
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


class TestEventLoggerConcurrency:
    """Test concurrent access to event logger."""

    @pytest.mark.asyncio
    async def test_concurrent_writes_should_not_corrupt_database(self):
        """
        Verify that concurrent writes don't cause database corruption.
        
        Multiple concurrent writes to the event logger should be
        properly serialized by the ThreadPoolExecutor.
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
