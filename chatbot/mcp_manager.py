import json
import shutil
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from . import config
from .logging_utils import InteractionLogger


class MCPManager:
    """Maneja las conexiones a los servidores MCP definidos en mcp_servers.json
    y expone sus tools al LLM en formato compatible con Claude."""

    def __init__(self, logger: InteractionLogger):
        self.logger = logger
        self._exit_stack = AsyncExitStack()
        self.sessions: dict[str, ClientSession] = {}
        self.tool_to_server: dict[str, str] = {}

    async def connect_all(self) -> None:
        for name, params in self._load_server_configs().items():
            await self._connect_server(name, params)

    def _load_server_configs(self) -> dict[str, dict]:
        if not config.MCP_SERVERS_CONFIG.exists():
            return {}
        data = json.loads(config.MCP_SERVERS_CONFIG.read_text(encoding="utf-8"))
        return data.get("mcpServers", {})

    @staticmethod
    def _expand_placeholders(value: str) -> str:
        value = value.replace("${WORKSPACE}", str(config.PROJECT_ROOT / "workspace"))
        value = value.replace("${SAT_TRACK_MCP_ROOT}", str(config.PROJECT_ROOT / "sat-track-mcp"))
        value = value.replace("${HOTEL_MCP_ROOT}", str(config.PROJECT_ROOT / "hotel-mcp-server"))
        value = value.replace("${PELICULAS_MCP_ROOT}", str(config.PROJECT_ROOT / "mpc-server-peliculas"))
        return value

    async def _connect_server(self, name: str, params: dict) -> None:
        command = self._expand_placeholders(params["command"])
        # busca el comando en el PATH ("npx", "uvx", etc.) para que funcione en cualquier SO
        command = shutil.which(command) or command
        args = [self._expand_placeholders(arg) for arg in params.get("args", [])]
        cwd = self._expand_placeholders(params["cwd"]) if "cwd" in params else None
        env = {k: self._expand_placeholders(v) for k, v in params["env"].items()} if "env" in params else None
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        )
        read, write = await self._exit_stack.enter_async_context(stdio_client(server_params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self.sessions[name] = session

        tools = await session.list_tools()
        for tool in tools.tools:
            self.tool_to_server[tool.name] = name
        print(f"[MCP] connected to '{name}' ({len(tools.tools)} tools)")

    async def list_claude_tools(self) -> list[dict[str, Any]]:
        claude_tools = []
        for session in self.sessions.values():
            tools = await session.list_tools()
            for tool in tools.tools:
                claude_tools.append({
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.input_schema,
                })
        return claude_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> tuple[str, bool]:
        """Devuelve (texto, is_error). is_error=True si el servidor reporto una falla
        (ej. repo_path que no es un repositorio git valido)."""
        server_name = self.tool_to_server.get(tool_name)
        if server_name is None:
            raise ValueError(f"Unknown tool '{tool_name}'")
        session = self.sessions[server_name]

        self.logger.log_request(server_name, tool_name, arguments)
        try:
            result = await session.call_tool(tool_name, arguments)
        except Exception as exc:
            self.logger.log_error(server_name, tool_name, str(exc))
            raise

        text = "\n".join(block.text for block in result.content if hasattr(block, "text"))
        is_error = bool(getattr(result, "is_error", False))
        if is_error:
            self.logger.log_error(server_name, tool_name, text)
        else:
            self.logger.log_response(server_name, tool_name, text)
        return text, is_error

    async def close(self) -> None:
        await self._exit_stack.aclose()
