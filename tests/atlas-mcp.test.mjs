import assert from "node:assert/strict";
import { access, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { handleAtlasMcpRequest } from "../dist/infrastructure/mcp/atlas-server.js";

test("Atlas MCP exposes provider-neutral read-only tools without Obsidian", async () => {
  const listed = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 1, method: "tools/list" });
  assert.deepEqual(listed.result.tools.map((tool) => tool.name), ["atlas_status", "atlas_doctor", "atlas_profiles_list", "atlas_tickets_list", "atlas_ticket_get", "atlas_handoffs_list", "atlas_handoff_get", "atlas_session_get", "atlas_session_summary", "atlas_session_events", "atlas_session_promote"]);
  const status = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "atlas_status", arguments: {} } });
  assert.match(status.result.content[0].text, /"name":"Atlas"/);
});

test("read-only session tools do not initialize a missing session database", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-mcp-readonly-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const response = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 9, method: "tools/call", params: { name: "atlas_session_get", arguments: { sessionId: "missing" } } });
    assert.ok(response.error);
    await assert.rejects(access(path.join(root, "system", "sessions", "sessions.sqlite")));
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previous;
  }
});

test("Atlas MCP exposes bounded resources and prompt templates", async () => {
  const listedResources = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 3, method: "resources/list" });
  assert.deepEqual(listedResources.result.resources.map((resource) => resource.uri), ["atlas://status", "atlas://profiles", "atlas://tickets", "atlas://handoffs"]);
  const resource = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 4, method: "resources/read", params: { uri: "atlas://status" } });
  assert.match(resource.result.contents[0].text, /"name": "Atlas"/);
  const listedPrompts = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 5, method: "prompts/list" });
  assert.deepEqual(listedPrompts.result.prompts.map((prompt) => prompt.name), ["atlas_review_workspace", "atlas_review_ticket"]);
  const prompt = await handleAtlasMcpRequest({ jsonrpc: "2.0", id: 6, method: "prompts/get", params: { name: "atlas_review_ticket", arguments: { ticket: "T-1" } } });
  assert.match(prompt.result.messages[0].content.text, /T-1/);
});
