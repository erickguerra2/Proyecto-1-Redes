import json
from datetime import datetime, timezone
from pathlib import Path

from . import config


class InteractionLogger:
    """Logs every request/response exchanged with MCP servers, to console and to a JSONL file."""

    def __init__(self, log_dir: Path = config.LOGS_DIR):
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"mcp_interactions_{timestamp}.jsonl"

    def _write(self, entry: dict) -> None:
        entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def log_request(self, server: str, tool: str, arguments: dict) -> None:
        self._write({"direction": "request", "server": server, "tool": tool, "arguments": arguments})
        print(f"[MCP -> {server}] call {tool}({arguments})")

    def log_response(self, server: str, tool: str, result: str) -> None:
        self._write({"direction": "response", "server": server, "tool": tool, "result": result})
        print(f"[MCP <- {server}] {tool} -> {result}")

    def log_error(self, server: str, tool: str, error: str) -> None:
        self._write({"direction": "error", "server": server, "tool": tool, "error": error})
        print(f"[MCP !! {server}] {tool} failed: {error}")
