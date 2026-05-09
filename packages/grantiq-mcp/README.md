# @grantiq/mcp

Stdio bridge to the hosted GrantIQ MCP server. Lets MCP clients that
require a stdio launcher (e.g. some Claude Desktop install flows) talk
to the remote `https://mcp.grantiq.us/mcp/` endpoint.

```bash
GRANTIQ_API_KEY=grantiq-dev-key-001 npx -y @grantiq/mcp
```

For most clients you can skip this package entirely and connect to the
remote URL directly:

```bash
claude mcp add grantiq-mcp --url https://mcp.grantiq.us/mcp
```
