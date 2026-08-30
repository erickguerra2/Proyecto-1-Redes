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
  over stdio, exposes their tools to Claude, and dispatches tool calls
  (`chatbot/mcp_manager.py`). No servers are configured yet — that's added
  incrementally as each project phase (Filesystem/Git MCP servers, the
  satellite MCP server, remote servers) is implemented.

See [`CONTEXT.md`](CONTEXT.md) for the full project checklist and requirements.

## Requirements

- Python 3.10+
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

## Configuring MCP servers

Servers are declared in `mcp_servers.json`, using the same shape as Claude
Desktop's config file:

```json
{
  "mcpServers": {
    "example": {
      "command": "npx",
      "args": ["-y", "@some/mcp-server"],
      "env": {}
    }
  }
}
```

The chatbot launches each configured server over stdio at startup and makes
its tools available to Claude automatically.

## Project layout

```
chatbot/            chatbot host source code
  main.py           entry point / conversation loop
  mcp_manager.py     MCP client connections + tool dispatch
  logging_utils.py  MCP interaction logging
  config.py         environment/config loading
mcp_servers.json    declares which MCP servers to connect to
logs/               MCP interaction logs (gitignored)
sat-track-mcp/      satellite MCP server — separate public repo, nested here
docs/               report material (network layer analysis, conclusions, etc.)
```
