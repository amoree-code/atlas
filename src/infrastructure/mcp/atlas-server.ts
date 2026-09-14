import { readdir } from "node:fs/promises";
import { listTickets } from "../../interfaces/cli/tickets-command.js";
import { hasFailures, workspaceReport } from "../../application/doctor/workspace-doctor.js";
import { atlasPath } from "../../paths.js";
import { promoteSessionToKnowledge } from "../../application/memory/session-promotion.js";

type Request = { jsonrpc?: string; id?: number; method?: string; params?: Record<string, unknown> };
type Response = { jsonrpc: "2.0"; id?: number; result?: unknown; error?: { code: number; message: string } };

const tools = [
  { name: "atlas_status", description: "Return the Atlas runtime and workspace status.", annotations: { readOnlyHint: true }, inputSchema: { type: "object", properties: {}, additionalProperties: false } },
  { name: "atlas_doctor", description: "Run the read-only Atlas workspace health checks.", annotations: { readOnlyHint: true }, inputSchema: { type: "object", properties: {}, additionalProperties: false } },
  { name: "atlas_profiles_list", description: "List available Atlas profiles.", annotations: { readOnlyHint: true }, inputSchema: { type: "object", properties: {}, additionalProperties: false } },
  { name: "atlas_tickets_list", description: "List Atlas tickets, optionally filtered by state.", annotations: { readOnlyHint: true }, inputSchema: { type: "object", properties: { state: { type: "string" } }, additionalProperties: false } },
  { name: "atlas_session_promote", description: "Promote a completed session result into reviewed Atlas knowledge.", annotations: { readOnlyHint: false }, inputSchema: { type: "object", properties: { sessionId: { type: "string" }, target: { type: "string" }, approved: { type: "boolean" } }, required: ["sessionId", "approved"], additionalProperties: false } },
];

const resources = [
  { uri: "atlas://status", name: "Atlas status", description: "Current Atlas workspace health." },
  { uri: "atlas://profiles", name: "Atlas profiles", description: "Available Atlas role profiles." },
  { uri: "atlas://tickets", name: "Atlas tickets", description: "Current Atlas tickets." },
];

const prompts = [
  { name: "atlas_review_workspace", description: "Review Atlas workspace health and summarize actionable findings.", arguments: [] },
  { name: "atlas_review_ticket", description: "Review one Atlas ticket and identify its next verified action.", arguments: [{ name: "ticket", description: "Ticket identifier", required: true }] },
];

function textResult(value: unknown): { content: [{ type: "text"; text: string }]; structuredContent: unknown } {
  return { content: [{ type: "text", text: JSON.stringify(value) }], structuredContent: value };
}

async function profiles(): Promise<string[]> {
  try { return (await readdir(atlasPath("system", "profiles"), { withFileTypes: true })).filter((entry) => entry.isFile() && entry.name.endsWith(".json")).map((entry) => entry.name.slice(0, -5)).sort(); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}

async function callTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  if (name === "atlas_status") return { name: "Atlas", version: "0.3.6", workspace: atlasPath(), mcp: "stdio" };
  if (name === "atlas_doctor") {
    const report = await workspaceReport();
    return { healthy: !hasFailures(report.findings), findings: report.findings };
  }
  if (name === "atlas_profiles_list") return { profiles: await profiles() };
  if (name === "atlas_tickets_list") return { tickets: await listTickets(typeof args.state === "string" ? args.state : undefined) };
  if (name === "atlas_session_promote") {
    if (args.approved !== true) throw new Error("Session promotion requires approved: true");
    return promoteSessionToKnowledge(requiredArgument(args, "sessionId"), typeof args.target === "string" ? args.target : "knowledge/results", true);
  }
  throw new Error(`Unknown MCP tool: ${name}`);
}

async function readResource(uri: string): Promise<{ uri: string; mimeType: string; text: string }> {
  let value: unknown;
  if (uri === "atlas://status") {
    const report = await workspaceReport();
    value = { name: "Atlas", version: "0.3.6", workspace: atlasPath(), healthy: !hasFailures(report.findings), findings: report.findings };
  } else if (uri === "atlas://profiles") value = { profiles: await profiles() };
  else if (uri === "atlas://tickets") value = { tickets: await listTickets() };
  else throw new Error(`Unknown Atlas resource: ${uri}`);
  return { uri, mimeType: "application/json", text: JSON.stringify(value, null, 2) };
}

function requiredArgument(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  if (typeof value !== "string" || !value) throw new Error(`${key} is required`);
  return value;
}

async function getPrompt(name: string, args: Record<string, unknown>): Promise<unknown> {
  if (name === "atlas_review_workspace") return { description: "Atlas workspace review", messages: [{ role: "user", content: { type: "text", text: "Run atlas_doctor and summarize only actionable findings. Do not change files." } }] };
  if (name === "atlas_review_ticket") {
    const ticket = requiredArgument(args, "ticket");
    return { description: `Review ${ticket}`, messages: [{ role: "user", content: { type: "text", text: `Read the Atlas ticket ${ticket}, report PROVEN, NOT PROVEN, or BLOCKED, and propose exactly one next verified action.` } }] };
  }
  throw new Error(`Unknown Atlas prompt: ${name}`);
}

export async function handleAtlasMcpRequest(request: Request): Promise<Response | null> {
  if (request.method === "notifications/initialized") return null;
  if (request.method === "initialize") return { jsonrpc: "2.0", id: request.id, result: { protocolVersion: "2025-06-18", capabilities: { tools: {}, resources: {}, prompts: {} }, serverInfo: { name: "atlas", version: "0.3.6" } } };
  if (request.method === "tools/list") return { jsonrpc: "2.0", id: request.id, result: { tools } };
  if (request.method === "resources/list") return { jsonrpc: "2.0", id: request.id, result: { resources } };
  if (request.method === "resources/read") {
    try { return { jsonrpc: "2.0", id: request.id, result: { contents: [await readResource(String(request.params?.uri ?? ""))] } }; }
    catch (error) { return { jsonrpc: "2.0", id: request.id, error: { code: -32000, message: error instanceof Error ? error.message : String(error) } }; }
  }
  if (request.method === "prompts/list") return { jsonrpc: "2.0", id: request.id, result: { prompts } };
  if (request.method === "prompts/get") {
    try { return { jsonrpc: "2.0", id: request.id, result: await getPrompt(String(request.params?.name ?? ""), (request.params?.arguments ?? {}) as Record<string, unknown>) }; }
    catch (error) { return { jsonrpc: "2.0", id: request.id, error: { code: -32000, message: error instanceof Error ? error.message : String(error) } }; }
  }
  if (request.method !== "tools/call") return { jsonrpc: "2.0", id: request.id, error: { code: -32601, message: `Unsupported MCP method: ${request.method ?? ""}` } };
  const name = request.params?.name;
  if (typeof name !== "string" || !tools.some((tool) => tool.name === name)) return { jsonrpc: "2.0", id: request.id, error: { code: -32602, message: "Unknown MCP tool" } };
  try { return { jsonrpc: "2.0", id: request.id, result: textResult(await callTool(name, (request.params?.arguments ?? {}) as Record<string, unknown>)) }; }
  catch (error) { return { jsonrpc: "2.0", id: request.id, error: { code: -32000, message: error instanceof Error ? error.message : String(error) } }; }
}

export async function runAtlasMcpServer(): Promise<void> {
  let buffer = Buffer.alloc(0);
  process.stdin.on("data", async (chunk: Buffer) => {
    buffer = Buffer.concat([buffer, chunk]);
    while (true) {
      const separator = buffer.indexOf("\r\n\r\n"); if (separator < 0) return;
      const match = /^Content-Length:\s*(\d+)/i.exec(buffer.subarray(0, separator).toString()); if (!match) throw new Error("Invalid MCP request headers");
      const length = Number(match[1]); const start = separator + 4; if (buffer.length < start + length) return;
      const request = JSON.parse(buffer.subarray(start, start + length).toString()) as Request; buffer = buffer.subarray(start + length);
      const response = await handleAtlasMcpRequest(request); if (!response) continue;
      const body = Buffer.from(JSON.stringify(response)); process.stdout.write(`Content-Length: ${body.length}\r\n\r\n`); process.stdout.write(body);
    }
  });
  await new Promise<void>((resolve) => process.stdin.once("end", resolve));
}
