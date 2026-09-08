"""Web front end for the Satellite Ops Assistant. Same conversation engine
and MCPManager as the console chatbot (chatbot/main.py) — this only swaps
the terminal loop for a WebSocket, per browser tab, driving a small chat UI.

Run with: python -m chatbot.web
"""

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import config
from .engine import handle_turn
from .logging_utils import InteractionLogger
from .mcp_manager import MCPManager

STATIC_DIR = Path(__file__).parent / "web_static"

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.ANTHROPIC_API_KEY:
        print("ERROR: set ANTHROPIC_API_KEY in a .env file (see .env.example).")
        sys.exit(1)

    state["client"] = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    logger = InteractionLogger()
    mcp = MCPManager(logger)
    await mcp.connect_all()
    state["mcp"] = mcp
    try:
        yield
    finally:
        await mcp.close()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.websocket("/ws")
async def chat_socket(websocket: WebSocket) -> None:
    await websocket.accept()

    messages: list[dict] = []
    # Same two-step write gate as the console chatbot (chatbot/engine.py) —
    # kept per-connection so one browser tab is one conversation.
    write_confirmation_state = {"preview_turn": None}
    turn_number = 0

    async def emit(event: dict[str, Any]) -> None:
        await websocket.send_json(event)

    try:
        while True:
            user_input = (await websocket.receive_text()).strip()
            if not user_input:
                continue

            turn_number += 1
            messages.append({"role": "user", "content": user_input})
            try:
                await handle_turn(
                    state["client"], state["mcp"], messages, turn_number, write_confirmation_state, emit
                )
            except Exception as exc:
                await emit({"type": "error", "text": str(exc)})
    except WebSocketDisconnect:
        pass


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
