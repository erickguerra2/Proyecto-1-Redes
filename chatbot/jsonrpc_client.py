"""Hand-rolled MCP client: speaks JSON-RPC 2.0 directly to MCP servers, over
both transports this project uses (stdio and Streamable HTTP), without the
`mcp` SDK on the host/client side. Framing, request/response correlation and
the initialize handshake are all implemented here instead of imported.

Servers on the other end (the official Filesystem/Git servers, the
classmates' servers, our own sat-track-mcp, the Cloudflare Worker) are free
to use the SDK themselves — this only removes it from *our* side of the wire,
which is the "implement MCP with raw JSON-RPC, no SDK" project extra.

Wire format: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

import asyncio
import itertools
import json
import subprocess
import sys
from contextlib import suppress
from typing import Any

import httpx2 as httpx

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "satellite-ops-chatbot", "version": "1.0.0"}

# Same curated inherit-list the official SDK uses, so npx/uvx/python
# subprocesses can still find node, the Windows DLL search path, etc.
# Anything server-specific rides in on top via each config's own "env".
_INHERITED_ENV_VARS = (
    ["APPDATA", "HOMEDRIVE", "HOMEPATH", "LOCALAPPDATA", "PATH", "PATHEXT",
     "PROCESSOR_ARCHITECTURE", "SYSTEMDRIVE", "SYSTEMROOT", "TEMP", "USERNAME", "USERPROFILE"]
    if sys.platform == "win32"
    else ["HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER"]
)

# Response lines can be large (directory trees, base64 receipts, DSP output);
# asyncio's default StreamReader limit (64 KiB) is too tight for that.
_STDIO_LINE_LIMIT = 10 * 1024 * 1024


def _default_environment() -> dict[str, str]:
    import os
    env = {k: v for k in _INHERITED_ENV_VARS if (v := os.environ.get(k)) is not None}
    # Forces UTF-8 for any spawned Python server's stdio, regardless of the
    # OS's default codepage (a non-ASCII character, e.g. an em dash in a
    # server's own name, otherwise lands on Windows's cp1252 by default and
    # breaks JSON parsing on our end). Harmless for non-Python commands.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


class McpProtocolError(RuntimeError):
    """A JSON-RPC error object came back from the server."""


class _IdCounter:
    def __init__(self) -> None:
        self._counter = itertools.count(1)

    def next(self) -> int:
        return next(self._counter)


class StdioJsonRpcSession:
    """One MCP session over a child process's stdin/stdout, framed as
    newline-delimited JSON-RPC 2.0 messages — the MCP stdio transport."""

    @classmethod
    async def spawn(
        cls,
        command: str,
        args: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> "StdioJsonRpcSession":
        full_env = _default_environment() | (env or {})
        creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            cwd=cwd,
            env=full_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,  # inherited, so server-side logs still reach the console
            limit=_STDIO_LINE_LIMIT,
            creationflags=creationflags,
        )
        return cls(process)

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._ids = _IdCounter()
        self._pending: dict[int, asyncio.Future] = {}
        self._write_lock = asyncio.Lock()
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._process.stdout is not None
        try:
            while True:
                raw_line = await self._process.stdout.readline()
                if not raw_line:
                    break
                # Some servers inherit the OS's default codepage on Windows
                # instead of forcing UTF-8 on their own stdout (we also pass
                # PYTHONIOENCODING=utf-8 to head that off), so decode
                # leniently rather than letting one bad byte take the reader
                # loop down.
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    # A well-behaved server never writes non-JSON-RPC to stdout,
                    # but don't take the whole session down if one does.
                    continue
                msg_id = message.get("id")
                future = self._pending.pop(msg_id, None) if msg_id is not None else None
                if future is not None and not future.done():
                    future.set_result(message)
        finally:
            # However this loop ends, whether the process exited or an
            # unexpected error above escaped the try, no pending request
            # should be left to hang for its full timeout: fail them now.
            error = ConnectionError("stdio reader loop ended before a response arrived")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()

    async def _send(self, payload: dict) -> None:
        assert self._process.stdin is not None
        data = (json.dumps(payload) + "\n").encode("utf-8")
        async with self._write_lock:
            self._process.stdin.write(data)
            await self._process.stdin.drain()

    async def request(self, method: str, params: dict | None = None, timeout: float = 120.0) -> Any:
        req_id = self._ids.next()
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = future
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)
        try:
            message = await asyncio.wait_for(future, timeout=timeout)
        finally:
            self._pending.pop(req_id, None)
        if "error" in message:
            err = message["error"]
            raise McpProtocolError(f"{method}: {err.get('message')} (code {err.get('code')})")
        return message.get("result")

    async def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._send(payload)

    async def initialize(self) -> None:
        await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        await self.notify("notifications/initialized")

    async def list_tools(self) -> list[dict]:
        result = await self.request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def close(self) -> None:
        self._reader_task.cancel()
        if self._process.stdin is not None and not self._process.stdin.is_closing():
            self._process.stdin.close()
            with suppress(Exception):
                await self._process.stdin.wait_closed()
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()


class HttpJsonRpcSession:
    """One MCP session over the Streamable HTTP transport: JSON-RPC 2.0
    requests POSTed to a single endpoint. A response is either a plain JSON
    body or a one-shot SSE stream (`text/event-stream`, `data: <json>` lines)
    — both are handled here."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = httpx.AsyncClient(timeout=120.0)
        self._ids = _IdCounter()
        self._session_id: str | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        return headers

    @staticmethod
    def _parse_body(content_type: str, text: str) -> dict:
        if "text/event-stream" in content_type:
            for line in text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[len("data:"):].strip())
            raise McpProtocolError("SSE response carried no data: line")
        return json.loads(text)

    async def _post(self, payload: dict) -> httpx.Response:
        response = await self._client.post(self._url, headers=self._headers(), json=payload)
        response.raise_for_status()
        session_id = response.headers.get("mcp-session-id")
        if session_id:
            self._session_id = session_id
        return response

    async def request(self, method: str, params: dict | None = None) -> Any:
        req_id = self._ids.next()
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            payload["params"] = params
        response = await self._post(payload)
        message = self._parse_body(response.headers.get("content-type", ""), response.text)
        if "error" in message:
            err = message["error"]
            raise McpProtocolError(f"{method}: {err.get('message')} (code {err.get('code')})")
        return message.get("result")

    async def notify(self, method: str, params: dict | None = None) -> None:
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        await self._post(payload)

    async def initialize(self) -> None:
        await self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
        })
        await self.notify("notifications/initialized")

    async def list_tools(self) -> list[dict]:
        result = await self.request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, name: str, arguments: dict) -> dict:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def close(self) -> None:
        await self._client.aclose()
