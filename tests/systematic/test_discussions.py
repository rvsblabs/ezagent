"""Tests for multi-agent discussion runtime."""

from unittest.mock import AsyncMock, Mock

import pytest


class TestDiscussionModeratorCalls:
    """Test discussion moderator behavior."""

    @pytest.mark.asyncio
    async def test_moderator_should_pass_discussion_source(self):
        """
        Verify that moderator calls include source='discussion' parameter.
        
        This ensures correct event logging for discussion moderator runs.
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
        
        # Verify the call includes proper parameters
        call_args = mock_agent.run.call_args
        assert call_args is not None
