import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { handleObsidianMcpRequest } from "../dist/infrastructure/mcp/obsidian-server.js";

test("Obsidian MCP exposes bounded tools and requires approval for writes", async () => {
  const vaultPath = await mkdtemp(path.join(os.tmpdir(), "atlas-obsidian-mcp-"));
  await writeFile(path.join(vaultPath, "note.md"), "# Note\n");
  const connection = { enabled: true, mode: "read-only", vaultPath };
  const listed = await handleObsidianMcpRequest({ jsonrpc: "2.0", id: 1, method: "tools/list" }, connection);
  assert.equal(listed.result.tools.length, 7);
  const read = await handleObsidianMcpRequest({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "obsidian_read", arguments: { path: "note.md" } } }, connection);
  assert.match(read.result.content[0].text, /# Note/);
  const rejected = await handleObsidianMcpRequest({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "obsidian_write", arguments: { path: "note.md", content: "changed", approved: false } } }, connection);
  assert.match(rejected.error.message, /approved/);
});
