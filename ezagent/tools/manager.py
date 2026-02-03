from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport, UvStdioTransport


class ToolManager:
    """Manages FastMCP tool clients and agent-as-tool synthetic tools."""

    def __init__(
        self,
        project_dir: Path,
        tool_names: List[str],
        agent_names: List[str],
        external_tool_paths: Optional[Dict[str, Path]] = None,
    ):
        self._project_dir = project_dir
        self._tool_names = [t for t in tool_names if t not in agent_names]
        self._agent_tool_names = [t for t in tool_names if t in agent_names]
        self._external_tool_paths = external_tool_paths or {}
        self._clients: Dict[str, Client] = {}
        self._tool_schemas: Dict[str, Dict[str, Any]] = {}
        # Maps tool function name -> (client_key, original_name)
        self._tool_routing: Dict[str, tuple[str, str]] = {}

    async def _connect_tool_dir(self, tool_name: str, tool_dir: Path):
        """Connect to a single MCP tool server in the given directory."""
        main_py = tool_dir / "main.py"
        if not main_py.is_file():
            raise FileNotFoundError(f"Tool main.py not found: {main_py}")

        pyproject = tool_dir / "pyproject.toml"
        requirements = tool_dir / "requirements.txt"

        if pyproject.is_file():
            transport = UvStdioTransport(
                command=str(main_py),
                project_directory=tool_dir,
            )
        elif requirements.is_file():
            transport = UvStdioTransport(
                command=str(main_py),
                with_requirements=requirements,
            )
        else:
            transport = PythonStdioTransport(script_path=str(main_py))
        client = Client(transport)
        await client.__aenter__()
        self._clients[tool_name] = client

        # List tools from this MCP server
        tools = await client.list_tools()
        for tool in tools:
            schema = self._mcp_to_anthropic_schema(tool_name, tool)
            qualified_name = schema["name"]
            self._tool_schemas[qualified_name] = schema
            self._tool_routing[qualified_name] = (tool_name, tool.name)

    async def connect(self):
        """Connect to all MCP tool servers and collect schemas."""
        tools_dir = self._project_dir / "tools"

        for tool_name in self._tool_names:
            tool_dir = tools_dir / tool_name
            await self._connect_tool_dir(tool_name, tool_dir)

        # Connect external (git-cloned) tools
        for tool_name, tool_dir in self._external_tool_paths.items():
            await self._connect_tool_dir(tool_name, tool_dir)

        # Register synthetic agent-as-tool schemas
        for agent_name in self._agent_tool_names:
            schema = {
                "name": f"agent_{agent_name}",
                "description": f"Delegate a task to the '{agent_name}' agent. Send a message and get back the agent's response.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The message or task to send to the agent.",
                        }
                    },
                    "required": ["message"],
                },
            }
            self._tool_schemas[schema["name"]] = schema

    def _mcp_to_anthropic_schema(
        self, tool_dir_name: str, mcp_tool: Any
    ) -> Dict[str, Any]:
        """Convert an MCP tool schema to Anthropic tool format."""
        # Namespace tool names to avoid collisions: tooldir__toolname
        qualified_name = f"{tool_dir_name}__{mcp_tool.name}"
        input_schema = (
            mcp_tool.inputSchema
            if hasattr(mcp_tool, "inputSchema") and mcp_tool.inputSchema
            else {"type": "object", "properties": {}}
        )
        return {
            "name": qualified_name,
            "description": mcp_tool.description or "",
            "input_schema": input_schema,
        }

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """Return all tool schemas in Anthropic format."""
        return list(self._tool_schemas.values())

    def is_agent_tool(self, tool_name: str) -> Optional[str]:
        """If tool_name is an agent-as-tool, return the agent name. Else None."""
        for agent_name in self._agent_tool_names:
            if tool_name == f"agent_{agent_name}":
                return agent_name
        return None

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Dispatch a tool call to the appropriate MCP client."""
        if tool_name not in self._tool_routing:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

        client_key, original_name = self._tool_routing[tool_name]
        client = self._clients[client_key]

        result = await client.call_tool(original_name, arguments)
        # FastMCP returns content blocks; extract text
        if hasattr(result, "content"):
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else str(result)
        return str(result)

    async def disconnect(self):
        """Disconnect all MCP clients."""
        for client in self._clients.values():
            try:
                await client.__aexit__(None, None, None)
            except Exception:
                pass
        self._clients.clear()
