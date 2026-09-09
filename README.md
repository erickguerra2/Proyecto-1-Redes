# Satellite Ops Assistant — MCP Chatbot Host

Console chatbot for Universidad del Valle de Guatemala's CC3067 Networks course
(Project 1: "Uso de un protocolo existente"). It acts as an MCP **host**: it
connects to the Anthropic API and to one or more **Model Context Protocol (MCP)**
servers (local and remote) to extend an LLM with real-world tools.

**Use case:** a Gen AI assistant for a satellite operations center. An operator
asks natural-language questions about a satellite (by name or NORAD ID): its
current status, upcoming visible passes from a given location, and whether it
is at risk of a close approach (conjunction) with another catalogued object.
Orbital calculations are served by a separate, purpose-built MCP server,
[`sat-track-mcp`](https://github.com/erickguerra2/sat-track-mcp) (public repo,
independent of this one).

## Status

This repository currently implements:

- Connection to the Anthropic API (`chatbot/main.py`).
- Session context: the conversation history is kept across turns.
- Logging of every MCP request/response, to the console and to a JSONL file
  under `logs/` (`chatbot/logging_utils.py`).
- An `MCPManager` that connects to every server listed in `mcp_servers.json`
  and dispatches tool calls (`chatbot/mcp_manager.py`), on top of a
  hand-rolled MCP client (`chatbot/jsonrpc_client.py`) — the host speaks
  JSON-RPC 2.0 directly over both stdio and Streamable HTTP itself (framing,
  the `initialize` handshake, request/response correlation), without the
  `mcp` SDK on the client side. The `mcp` package isn't even installed in
  this project's own `.venv` — servers on the other end are free to use it
  themselves (several do).
- The official **Filesystem MCP server** and **Git MCP server** (Anthropic),
  wired in via `mcp_servers.json`, scoped to the `workspace/` sandbox
  directory so the chatbot can create a repo, write a README, stage it, and
  commit — all from natural-language instructions.
- The satellite MCP server (`sat-track-mcp/`), a purpose-built server for the
  satellite ops use case.
- Three classmates' MCP servers, wired in the same way (only two are
  required by the project — the third is extra): `hotel-mcp-server`
  (JosFer720), `mpc-server-peliculas` (Albu231311, a movie-rental store
  server), and `mixassist-mcp-server` (diegoanro22, audio mix analysis —
  loudness/LUFS, spectrum, clipping — over real DSP).
- A host-side gate on `hotel-mcp-server`'s two-step write flow
  (`crear_reservacion`): a `confirmado: true` call is only accepted if the
  preview call happened on an earlier user turn, so the model can't chain
  preview + confirm in a single reply and write before the user actually
  approved anything.
- A remote MCP server (`remote-mcp-server/`), deployed to Cloudflare Workers
  and reachable over Streamable HTTP instead of stdio — see its own
  [README](remote-mcp-server/README.md). `MCPManager` connects to it the same
  way as the stdio servers, branching on a `url` key in `mcp_servers.json`.
- A web GUI (`chatbot/web.py`, optional extra) — the console remains the
  required way to run the project, but the same conversation engine
  (`chatbot/engine.py`) is also served over a WebSocket to a small browser
  chat UI (`chatbot/web_static/index.html`) that shows tool calls and their
  results inline as they happen, not just the final answer. It also has a
  file attach button (`POST /upload`) so a local file (e.g. audio for
  `mixassist-mcp-server`) reaches a tool by path without typing one.

## Requirements

- Python 3.10+
- Node.js (for `npx`, used to run the Filesystem MCP server)
- [`uv`](https://docs.astral.sh/uv/) (for `uvx`, used to run the Git MCP server)
- An [Anthropic API key](https://console.anthropic.com/)

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # then edit .env and set ANTHROPIC_API_KEY
```

## Usage

```bash
python -m chatbot.main
```

Type your question at the `you>` prompt. Type `exit` to quit. Any MCP tool
call made during the conversation is printed to the console and appended to
`logs/mcp_interactions_<timestamp>.jsonl`.

### Optional: web GUI

```bash
python -m chatbot.web
```

Then open http://127.0.0.1:8000. This is the same chatbot and the same
`MCPManager`/MCP servers — only the front end differs, so MCP interactions
are still logged to `logs/` exactly as in the console version.

## Protocol implementation: raw JSON-RPC, no MCP SDK

`chatbot/jsonrpc_client.py` is the MCP client, implemented by hand instead of
using the official `mcp` Python SDK (which isn't a dependency of this
project's `.venv` at all — see `requirements.txt`):

- **Stdio transport** (`StdioJsonRpcSession`): spawns the server subprocess
  with `asyncio.create_subprocess_exec`, writes newline-delimited JSON-RPC 2.0
  requests to its stdin, and a background task reads its stdout line by line,
  parses each line as JSON, and resolves the matching pending request by
  `id` — the same request/response correlation `ClientSession` normally does
  internally.
- **Streamable HTTP transport** (`HttpJsonRpcSession`): POSTs JSON-RPC
  requests to the server's URL and parses the response body itself, whether
  the server answers with a plain `application/json` object or a one-shot
  `text/event-stream` (`data: <json>` lines) — this is how the remote
  Cloudflare Worker is reached.
- Both implement the same minimal surface: `initialize()` (sends the
  `initialize` request, then the `notifications/initialized` notification —
  the MCP lifecycle handshake), `list_tools()`, `call_tool()`, `close()`.
  `MCPManager` only talks to that surface, so it doesn't know or care which
  transport a given server uses.

The servers on the other end of the wire (the official Filesystem/Git
servers, the classmates' servers, `sat-track-mcp`, the Cloudflare Worker) are
unaffected and free to use the SDK on their own side — this only removes it
from the host's side of the protocol.

## Configuring MCP servers

Servers are declared in `mcp_servers.json`, using the same shape as Claude
Desktop's config file. `${WORKSPACE}` expands to the absolute path of the
`workspace/` sandbox directory:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "${WORKSPACE}"]
    },
    "git": {
      "command": "uvx",
      "args": ["mcp-server-git"]
    }
  }
}
```

The chatbot launches each configured server over stdio at startup and makes
its tools available to Claude automatically. The Filesystem server is scoped
to `workspace/` so the chatbot can only read/write inside that sandbox, not
across the rest of the project.

A server can also be declared with a `url` instead of `command`/`args`, in
which case the host connects over Streamable HTTP instead of spawning a
local process — this is how the remote Cloudflare Worker is wired in:

```json
{
  "mcpServers": {
    "satellite-remote": {
      "url": "https://satellite-remote-mcp.erickguerra2.workers.dev/mcp"
    }
  }
}
```

## Project layout

```
chatbot/            chatbot host source code
  main.py           console entry point / conversation loop
  web.py            optional web GUI entry point (FastAPI + WebSocket + /upload)
  web_static/       browser chat UI served by web.py
  engine.py         conversation engine shared by main.py and web.py
  mcp_manager.py     server config, tool dispatch, per-server sessions
  jsonrpc_client.py  hand-rolled MCP client (JSON-RPC 2.0, no mcp SDK)
  logging_utils.py  MCP interaction logging
  config.py         environment/config loading
mcp_servers.json    declares which MCP servers to connect to
logs/               MCP interaction logs (gitignored)
workspace/          sandbox the Filesystem/Git MCP servers operate on (gitignored)
uploads/            files attached from the web GUI (gitignored)
sat-track-mcp/          satellite MCP server — separate public repo, nested here
hotel-mcp-server/       classmate's MCP server (gitignored, cloned locally)
mpc-server-peliculas/   classmate's MCP server (gitignored, cloned locally)
mixassist-mcp-server/   classmate's MCP server (gitignored, cloned locally)
remote-mcp-server/      our own remote MCP server, deployed to Cloudflare Workers
docs/                   report material (network layer analysis, conclusions, etc.)
```
