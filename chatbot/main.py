import asyncio
import sys
from typing import Any

import anthropic

# fuerza UTF-8 en consola de Windows para que tildes/enies no salgan mal
sys.stdout.reconfigure(encoding="utf-8")
sys.stdin.reconfigure(encoding="utf-8")

from . import config
from .engine import handle_turn
from .logging_utils import InteractionLogger
from .mcp_manager import MCPManager


async def console_emit(event: dict[str, Any]) -> None:
    if event["type"] == "text":
        print(f"claude> {event['text']}")


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
            await handle_turn(client, mcp, messages, turn_number, write_confirmation_state, console_emit)
    finally:
        await mcp.close()


def main() -> None:
    asyncio.run(run_chat())


if __name__ == "__main__":
    main()
