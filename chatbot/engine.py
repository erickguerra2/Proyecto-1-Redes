"""Conversation engine shared by the console (chatbot/main.py) and web
(chatbot/web.py) front ends: one turn = one call to Claude, followed by
however many MCP tool round-trips it asks for."""

import json
from typing import Any, Awaitable, Callable

import anthropic

from . import config
from .mcp_manager import MCPManager

SYSTEM_PROMPT = (
    "You are the Gen AI assistant for a satellite operations center. You help an "
    "operator query information about satellites in orbit: their current status, "
    "when they are visible from a given location, and whether there is a "
    "close-approach (conjunction) risk with another catalogued object. "
    "Use the available MCP tools whenever the question requires them."
)

# Emits one event dict as the turn progresses, so a front end can render it
# live instead of waiting for the whole turn to finish. Event shapes:
#   {"type": "text", "text": str}
#   {"type": "tool_call", "name": str, "arguments": dict, "server": str, "remote": bool}
#   {"type": "tool_result", "name": str, "is_error": bool, "result": str, "server": str, "remote": bool}
# "server" is the mcp_servers.json key (e.g. "satellite" vs "satellite-remote")
# and "remote" says whether that server was reached over a URL instead of a
# local subprocess -- both let a front end show at a glance which server a
# call actually went to.
Emit = Callable[[dict[str, Any]], Awaitable[None]]


def _server_info(mcp: MCPManager, tool_name: str) -> dict[str, Any]:
    server = mcp.tool_to_server.get(tool_name)
    return {"server": server, "remote": mcp.server_is_remote.get(server, False)}


async def handle_turn(
    client: anthropic.Anthropic,
    mcp: MCPManager,
    messages: list[dict],
    turn_number: int,
    write_confirmation_state: dict,
    emit: Emit,
) -> None:
    tools = await mcp.list_claude_tools()

    while True:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=config.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=tools,
        )

        assistant_content = response.content
        messages.append({"role": "assistant", "content": assistant_content})

        for block in assistant_content:
            if block.type == "text":
                await emit({"type": "text", "text": block.text})

        tool_uses = [block for block in assistant_content if block.type == "tool_use"]
        if not tool_uses:
            return

        tool_results = []
        for tool_use in tool_uses:
            server_info = _server_info(mcp, tool_use.name)
            await emit({"type": "tool_call", "name": tool_use.name, "arguments": tool_use.input, **server_info})

            if tool_use.name == "crear_reservacion" and tool_use.input.get("confirmado"):
                preview_turn = write_confirmation_state["preview_turn"]
                if preview_turn is None or preview_turn >= turn_number:
                    result_text = (
                        "Blocked by the host: crear_reservacion needs a preview call "
                        "(without confirmado) shown to the user in an earlier turn before "
                        "confirmado=true is allowed. Call it again without confirmado, "
                        "show the details, and wait for the user's next message."
                    )
                    is_error = True
                    await emit({"type": "tool_result", "name": tool_use.name, "is_error": is_error, "result": result_text, **server_info})
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "content": result_text,
                        "is_error": is_error,
                    })
                    continue
                write_confirmation_state["preview_turn"] = None

            try:
                result_text, is_error = await mcp.call_tool(tool_use.name, tool_use.input)
            except Exception as exc:
                result_text, is_error = f"error: {exc}", True

            if tool_use.name == "crear_reservacion" and not is_error:
                try:
                    payload = json.loads(result_text)
                except json.JSONDecodeError:
                    payload = {}
                if payload.get("requiere_confirmacion"):
                    write_confirmation_state["preview_turn"] = turn_number

            await emit({"type": "tool_result", "name": tool_use.name, "is_error": is_error, "result": result_text, **server_info})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_text,
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})
