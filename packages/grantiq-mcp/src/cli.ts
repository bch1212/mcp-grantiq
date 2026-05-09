#!/usr/bin/env node
/**
 * GrantIQ MCP — local stdio bridge to the hosted remote server.
 *
 * Usage:
 *   GRANTIQ_API_KEY=grantiq-dev-key-001 npx grantiq-mcp
 *
 * The bridge forwards every stdio MCP request to https://mcp.grantiq.us/mcp/
 * with an `X-API-Key` header attached. Free dev key gives 50 calls/day; mint
 * a higher-limit key with `curl -X POST https://mcp.grantiq.us/admin/keys`.
 */
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const REMOTE_URL = process.env.GRANTIQ_REMOTE_URL ?? "https://mcp.grantiq.us/mcp/";
const API_KEY = process.env.GRANTIQ_API_KEY ?? "grantiq-dev-key-001";

async function main() {
  const remote = new Client({ name: "grantiq-mcp-bridge", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(new URL(REMOTE_URL), {
    requestInit: { headers: { "X-API-Key": API_KEY } },
  });
  await remote.connect(transport);

  const local = new Server(
    { name: "grantiq-mcp", version: "1.0.0" },
    { capabilities: { tools: {} } }
  );

  // Proxy tool list + calls through to the remote server.
  local.setRequestHandler({ method: "tools/list" } as any, async () => {
    const tools = await remote.listTools();
    return { tools: tools.tools };
  });
  local.setRequestHandler({ method: "tools/call" } as any, async (req: any) => {
    return await remote.callTool({
      name: req.params.name,
      arguments: req.params.arguments ?? {},
    });
  });

  await local.connect(new StdioServerTransport());
  process.stderr.write(`grantiq-mcp bridge connected → ${REMOTE_URL}\n`);
}

main().catch((err) => {
  process.stderr.write(`grantiq-mcp bridge error: ${err?.stack ?? err}\n`);
  process.exit(1);
});
