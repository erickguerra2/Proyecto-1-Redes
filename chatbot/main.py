import asyncio
import json
import sys

import anthropic

# fuerza UTF-8 en consola de Windows para que tildes/enies no salgan mal
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from . import config
from .logging_utils import InteractionLogger
from .mcp_manager import MCPManager

SYSTEM_PROMPT = (
    "You are the Gen AI assistant for a satellite operations center. You help an "
    "operator query information about satellites in orbit: their current status, "
    "when they are visible from a given location, and whether there is a "
    "close-approach (conjunction) risk with another catalogued object. "
    "Use the available MCP tools whenever the question requires them."
)


async def run_chat() -> None:
    if not config.ANTHROPIC_API_KEY:
        print("ERROR: set ANTHROPIC_API_KEY in a .env file (see .env.example).")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    logger = InteractionLogger()
    mcp = MCPManager(logger)
    await mcp.connect_all()

    messages: list[dict] = []
    # hotel_mcp's crear_reservacion is a two-step write: a preview call, then a
    # confirmado=true call. A server can't see where one user turn ends and the
    # next begins, so only the host can stop the model from chaining both calls
    # in a single reply and writing before the user actually approved anything.
    # We gate confirmado=true on the preview having happened on a *previous* turn.
    write_confirmation_state = {"preview_turn": None}
    turn_number = 0
    print("Satellite Ops Assistant — type 'exit' to quit.\n")

    try:
        while True:
            user_input = input("you> ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            turn_number += 1
            messages.append({"role": "user", "content": user_input})
            await handle_turn(client, mcp, messages, turn_number, write_confirmation_state)
    finally:
        await mcp.close()


async def handle_turn(
    client: anthropic.Anthropic,
    mcp: MCPManager,
    messages: list[dict],
    turn_number: int,
    write_confirmation_state: dict,
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
                print(f"claude> {block.text}")

        tool_uses = [block for block in assistant_content if block.type == "tool_use"]
        if not tool_uses:
            return

        tool_results = []
        for tool_use in tool_uses:
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

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_text,
                "is_error": is_error,
            })

        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    asyncio.run(run_chat())


if __name__ == "__main__":
    main()
