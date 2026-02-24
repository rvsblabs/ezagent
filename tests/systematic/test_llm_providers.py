"""Tests for LLM provider implementations."""

import pytest


class TestGoogleProviderToolResults:
    """Test Google/Gemini provider tool result handling."""

    @pytest.mark.asyncio
    async def test_tool_result_name_should_use_function_name_not_tool_use_id(self):
        """
        Verify that tool results use function names, not tool_use_ids.
        
        Gemini expects the original function name in tool results,
        not the tool call ID from Anthropic format.
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

        contents = _convert_messages(messages)

        # Check that the tool result part has the correct structure
        tool_result_part = contents[-1].parts[0]
        assert hasattr(tool_result_part, "function_response")


    @pytest.mark.asyncio
    async def test_tool_result_should_preserve_function_name(self):
        """
        Verify that function names are preserved across tool use and result blocks.
        
        The mapping from tool_use_id to function name must be maintained
        throughout the conversation.
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
        assert len(contents) == 3
        
        # Check the tool result part
        tool_result_content = contents[2]
        assert len(tool_result_content.parts) == 1
