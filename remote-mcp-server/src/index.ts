import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";

// ISS NORAD catalog id, used by the satellite ops chatbot's satellite-themed
// remote MCP server (Project 1, CC3067). Trivial by design: the point is to
// demonstrate a tool running remotely, not new orbital math.
const ISS_NORAD_ID = 25544;

function createServer() {
	const server = new McpServer({
		name: "satellite-remote-mcp",
		version: "1.0.0",
	});

	server.registerTool(
		"get_iss_location",
		{ inputSchema: z.object({}) },
		async () => {
			const response = await fetch(
				`https://api.wheretheiss.at/v1/satellites/${ISS_NORAD_ID}`,
			);
			if (!response.ok) {
				return {
					content: [
						{
							type: "text",
							text: `Error: upstream ISS tracking API returned ${response.status}`,
						},
					],
					isError: true,
				};
			}
			const data = await response.json();
			return { content: [{ type: "text", text: JSON.stringify(data) }] };
		},
	);

	return server;
}

const handler = createMcpHandler(createServer);

export default {
	fetch(request: Request, env: Env, ctx: ExecutionContext) {
		return handler(request, env, ctx);
	},
} satisfies ExportedHandler<Env>;
