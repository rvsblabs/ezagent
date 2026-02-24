"""Tests for configuration validation and loading."""

import tempfile
from pathlib import Path

import pytest


class TestConfigValidation:
    """Test configuration validation logic."""

    def test_circular_reference_through_discussions_should_be_allowed(self):
        """
        Verify that circular references through discussions are properly handled.
        
        Discussions are not part of the agent dependency graph, so agents
        can reference discussions that include them as participants.
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
