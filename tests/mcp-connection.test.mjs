import assert from "node:assert/strict";
import test from "node:test";
import { obsidianMcpConfig } from "../dist/application/mcp/mcp-connection.js";

test("generates one provider-neutral stdio MCP config", () => {
  const config = obsidianMcpConfig();
  assert.equal(config.mcpServers.atlas.type, "stdio");
  assert.equal(config.mcpServers.atlas.args.at(-2), "obsidian");
  assert.equal(config.mcpServers.atlas.args.at(-1), "mcp");
  assert.match(config.mcpServers.atlas.command, /node/);
});
