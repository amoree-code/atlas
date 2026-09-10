import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mcpToolSchema, type McpTool } from "../../domain/mcp/mcp-contract.js";

type JsonRpc = { jsonrpc: "2.0"; id?: number; method?: string; params?: unknown; result?: unknown; error?: { message?: string } };
export type McpClientOptions = { command: string; args?: string[]; cwd: string; allowedTools?: string[] };

export class McpClient {
  private child: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
  private buffer = Buffer.alloc(0);
  private tools = new Map<string, McpTool>();

  constructor(private readonly options: McpClientOptions) {}

  async connect(): Promise<void> {
    this.child = spawn(this.options.command, this.options.args ?? [], { cwd: this.options.cwd, stdio: "pipe" });
    this.child.stdout.on("data", (chunk: Buffer) => this.consume(chunk));
    this.child.once("error", (error) => this.failPending(error));
    this.child.once("close", () => this.failPending(new Error("MCP server stopped")));
    await this.request("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "atlas", version: "0.3.2" } });
    await this.request("notifications/initialized", {});
  }

  async listTools(): Promise<McpTool[]> {
    const result = await this.request("tools/list", {}) as { tools?: unknown[] };
    const tools = (result.tools ?? []).map((tool) => mcpToolSchema.parse(tool));
    this.tools = new Map(tools.map((tool) => [tool.name, tool]));
    return this.filterAllowed(tools);
  }

  async callTool(name: string, arguments_: Record<string, unknown> = {}, approval = false): Promise<unknown> {
    const tool = this.tools.get(name) ?? (await this.listTools()).find((candidate) => candidate.name === name);
    if (!tool) throw new Error(`MCP tool is not allowed or unavailable: ${name}`);
    if (!this.isAllowed(name)) throw new Error(`MCP tool is not allowed: ${name}`);
    if (tool.annotations?.readOnlyHint === false && !approval) throw new Error(`MCP write requires explicit approval: ${name}`);
    return this.request("tools/call", { name, arguments: arguments_ });
  }

  close(): void {
    if (this.child) {
      this.child.stdin.destroy();
      this.child.stdout.destroy();
      this.child.kill("SIGKILL");
    }
    this.child = null;
  }

  private isAllowed(name: string): boolean { return !this.options.allowedTools || this.options.allowedTools.includes(name); }
  private filterAllowed(tools: McpTool[]): McpTool[] { return tools.filter((tool) => this.isAllowed(tool.name)); }
  private request(method: string, params: unknown): Promise<unknown> {
    if (!this.child?.stdin.writable) return Promise.reject(new Error("MCP client is not connected"));
    const id = this.nextId++;
    const message = Buffer.from(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    this.child.stdin.write(`Content-Length: ${message.length}\r\n\r\n`); this.child.stdin.write(message);
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  private consume(chunk: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, chunk]);
    while (true) {
      const separator = this.buffer.indexOf("\r\n\r\n"); if (separator < 0) return;
      const match = /^Content-Length:\s*(\d+)/i.exec(this.buffer.subarray(0, separator).toString()); if (!match) throw new Error("Invalid MCP response headers");
      const length = Number(match[1]); const start = separator + 4; if (this.buffer.length < start + length) return;
      const response = JSON.parse(this.buffer.subarray(start, start + length).toString()) as JsonRpc;
      this.buffer = this.buffer.subarray(start + length); if (response.id === undefined) continue;
      const pending = this.pending.get(response.id); if (!pending) continue; this.pending.delete(response.id);
      if (response.error) pending.reject(new Error(`MCP ${response.error.message ?? "request failed"}`)); else pending.resolve(response.result);
    }
  }
  private failPending(error: Error): void { for (const pending of this.pending.values()) pending.reject(error); this.pending.clear(); }
}
