# Satellite Remote MCP Server

A remote MCP server for this project's satellite ops chatbot (UVG CC3067
Networks, Project 1, item 7: a remote MCP server deployed to the cloud). It
runs on [Cloudflare Workers](https://developers.cloudflare.com/workers/) and
speaks MCP over Streamable HTTP (no stdio, no local process) — the point of
this piece is to demonstrate the chatbot host talking to a server that
actually executes remotely, so the tool itself is intentionally trivial.

Deployed at: `https://satellite-remote-mcp.erickguerra2.workers.dev/mcp`

Based on Cloudflare's official `remote-mcp-authless` template
(`cloudflare/ai/demos/remote-mcp-authless`).

## Tool

| Tool | Parameters | Returns |
|---|---|---|
| `get_iss_location` | none | Current ISS position (latitude, longitude, altitude, velocity, visibility) from the public [wheretheiss.at](https://wheretheiss.at/) API |

## Local development

```bash
npm install
npm run dev        # serves http://localhost:8787/mcp
```

## Deploy

```bash
npx wrangler login   # one-time Cloudflare auth
npm run deploy
```

Deploying for the first time requires a `workers.dev` subdomain to be
registered once from the Cloudflare dashboard
(`Workers & Pages > your account > Workers.dev subdomain`) before
`wrangler deploy` will resolve publicly.

## Connecting from this project's chatbot

The host connects to it like any other MCP server, declared in
`mcp_servers.json` with a `url` instead of a `command` (see
`chatbot/mcp_manager.py`, which branches on that key to use
`streamable_http_client` instead of `stdio_client`):

```json
{
  "mcpServers": {
    "satellite-remote": {
      "url": "https://satellite-remote-mcp.erickguerra2.workers.dev/mcp"
    }
  }
}
```
