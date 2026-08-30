import asyncio
import sys

import anthropic

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
    print("Satellite Ops Assistant — type 'exit' to quit.\n")

    try:
        while True:
            user_input = input("you> ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})
            await handle_turn(client, mcp, messages)
    finally:
        await mcp.close()


async def handle_turn(client: anthropic.Anthropic, mcp: MCPManager, messages: list[dict]) -> None:
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
            try:
                result_text = await mcp.call_tool(tool_use.name, tool_use.input)
            except Exception as exc:
                result_text = f"error: {exc}"
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result_text,
            })

        messages.append({"role": "user", "content": tool_results})


def main() -> None:
    asyncio.run(run_chat())


if __name__ == "__main__":
    main()
