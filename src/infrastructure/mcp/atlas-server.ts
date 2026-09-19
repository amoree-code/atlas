import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import {
  hasFailures,
  workspaceReport,
} from "../../application/doctor/workspace-doctor.js";
import {
  getHandoff,
  getTicket,
  listHandoffs,
} from "../../application/handoff/handoff-service.js";
import { promoteSessionToKnowledge } from "../../application/memory/session-promotion.js";
import {
  actionFingerprint,
  mcpApprovalSchema,
} from "../../domain/mcp/mcp-contract.js";
import { listTickets } from "../../interfaces/cli/tickets-command.js";
import { atlasPath, atlasRoot } from "../../paths.js";
import { openSessionStoreReadOnly } from "../persistence/session-store.js";

type Request = {
  jsonrpc?: string;
  id?: number;
  method?: string;
  params?: Record<string, unknown>;
};
type Response = {
  jsonrpc: "2.0";
  id?: number;
  result?: unknown;
  error?: { code: number; message: string };
};

const tools = [
  {
    name: "atlas_status",
    description: "Return the Atlas runtime and workspace status.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "atlas_doctor",
    description: "Run the read-only Atlas workspace health checks.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "atlas_profiles_list",
    description: "List available Atlas profiles.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {},
      additionalProperties: false,
    },
  },
  {
    name: "atlas_tickets_list",
    description: "List Atlas tickets, optionally filtered by state.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: { state: { type: "string" } },
      additionalProperties: false,
    },
  },
  {
    name: "atlas_ticket_get",
    description: "Read one bounded Atlas ticket record.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: { ticketId: { type: "string" } },
      required: ["ticketId"],
      additionalProperties: false,
    },
  },
  {
    name: "atlas_handoffs_list",
    description: "List compact cross-client session handoffs.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: { ticketId: { type: "string" } },
      additionalProperties: false,
    },
  },
  {
    name: "atlas_handoff_get",
    description: "Read one bounded cross-client session handoff.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {
        handoffId: { type: "string" },
        maxBytes: { type: "number" },
      },
      required: ["handoffId"],
      additionalProperties: false,
    },
  },
  {
    name: "atlas_session_get",
    description: "Read one session metadata record without its transcript.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: { sessionId: { type: "string" } },
      required: ["sessionId"],
      additionalProperties: false,
    },
  },
  {
    name: "atlas_session_summary",
    description: "Read one bounded human-readable session summary.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {
        sessionId: { type: "string" },
        maxBytes: { type: "number" },
      },
      required: ["sessionId"],
      additionalProperties: false,
    },
  },
  {
    name: "atlas_session_events",
    description:
      "Read one bounded session event log explicitly requested by id.",
    annotations: { readOnlyHint: true },
    inputSchema: {
      type: "object",
      properties: {
        sessionId: { type: "string" },
        maxEvents: { type: "number" },
      },
      required: ["sessionId"],
      additionalProperties: false,
    },
  },
  {
    name: "atlas_session_promote",
    description:
      "Promote a completed session result into reviewed Atlas knowledge.",
    annotations: { readOnlyHint: false },
    inputSchema: {
      type: "object",
      properties: {
        sessionId: { type: "string" },
        target: { type: "string" },
        approval: { type: "object" },
      },
      required: ["sessionId", "approval"],
      additionalProperties: false,
    },
  },
];

const resources = [
  {
    uri: "atlas://status",
    name: "Atlas status",
    description: "Current Atlas workspace health.",
  },
  {
    uri: "atlas://profiles",
    name: "Atlas profiles",
    description: "Available Atlas role profiles.",
  },
  {
    uri: "atlas://tickets",
    name: "Atlas tickets",
    description: "Current Atlas tickets.",
  },
  {
    uri: "atlas://handoffs",
    name: "Atlas handoffs",
    description: "Compact cross-client session handoffs.",
  },
];

const prompts = [
  {
    name: "atlas_review_workspace",
    description:
      "Review Atlas workspace health and summarize actionable findings.",
    arguments: [],
  },
  {
    name: "atlas_review_ticket",
    description:
      "Review one Atlas ticket and identify its next verified action.",
    arguments: [
      { name: "ticket", description: "Ticket identifier", required: true },
    ],
  },
];

function textResult(value: unknown): {
  content: [{ type: "text"; text: string }];
  structuredContent: unknown;
} {
  return {
    content: [{ type: "text", text: JSON.stringify(value) }],
    structuredContent: value,
  };
}

async function profiles(): Promise<string[]> {
  try {
    return (
      await readdir(atlasPath("system", "profiles"), { withFileTypes: true })
    )
      .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
      .map((entry) => entry.name.slice(0, -5))
      .sort();
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function callTool(
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  if (name === "atlas_status")
    return {
      name: "Atlas",
      version: "0.3.6",
      workspace: atlasPath(),
      mcp: "stdio",
    };
  if (name === "atlas_doctor") {
    const report = await workspaceReport();
    return {
      healthy: !hasFailures(report.findings),
      findings: report.findings,
    };
  }
  if (name === "atlas_profiles_list") return { profiles: await profiles() };
  if (name === "atlas_tickets_list")
    return {
      tickets: await listTickets(
        typeof args.state === "string" ? args.state : undefined,
      ),
    };
  if (name === "atlas_ticket_get")
    return await getTicket(requiredArgument(args, "ticketId"));
  if (name === "atlas_handoffs_list")
    return {
      handoffs: await listHandoffs(
        typeof args.ticketId === "string" ? args.ticketId : undefined,
      ),
    };
  if (name === "atlas_handoff_get")
    return await getHandoff(
      requiredArgument(args, "handoffId"),
      typeof args.maxBytes === "number"
        ? Math.min(16_000, Math.max(512, args.maxBytes))
        : 8_000,
    );
  if (name === "atlas_session_get") {
    const store = await openSessionStoreReadOnly();
    try {
      const session = store.get(requiredArgument(args, "sessionId"));
      if (!session) throw new Error("Session not found");
      return session;
    } finally {
      store.close();
    }
  }
  if (name === "atlas_session_summary") {
    const store = await openSessionStoreReadOnly();
    try {
      const session = store.get(requiredArgument(args, "sessionId"));
      if (!session) throw new Error("Session not found");
      if (!session.summaryPath)
        throw new Error("Session summary not available");
      const summaryPath = path.resolve(atlasRoot(), session.summaryPath);
      const root = `${path.resolve(atlasPath("system", "sessions", "summaries"))}${path.sep}`;
      if (!summaryPath.startsWith(root))
        throw new Error(
          "Session summary path is outside the Atlas summary directory",
        );
      const maxBytes =
        typeof args.maxBytes === "number"
          ? Math.min(12_000, Math.max(512, args.maxBytes))
          : 12_000;
      return {
        sessionId: session.sessionId,
        summaryPath: session.summaryPath,
        summary: (await readFile(summaryPath, "utf8")).slice(0, maxBytes),
      };
    } finally {
      store.close();
    }
  }
  if (name === "atlas_session_events") {
    const store = await openSessionStoreReadOnly();
    try {
      const events = store.listEvents(requiredArgument(args, "sessionId"));
      const max =
        typeof args.maxEvents === "number"
          ? Math.min(100, Math.max(1, args.maxEvents))
          : 20;
      return { events: events.slice(-max) };
    } finally {
      store.close();
    }
  }
  if (name === "atlas_session_promote") {
    const approval = mcpApprovalSchema.parse(args.approval);
    const actionArgs = {
      sessionId: args.sessionId,
      target:
        typeof args.target === "string" ? args.target : "knowledge/results",
    };
    if (approval.fingerprint !== actionFingerprint(name, actionArgs))
      throw new Error(
        "Session promotion approval does not match the requested action",
      );
    return promoteSessionToKnowledge(
      requiredArgument(args, "sessionId"),
      typeof args.target === "string" ? args.target : "knowledge/results",
      true,
    );
  }
  throw new Error(`Unknown MCP tool: ${name}`);
}

async function readResource(
  uri: string,
): Promise<{ uri: string; mimeType: string; text: string }> {
  let value: unknown;
  if (uri === "atlas://status") {
    const report = await workspaceReport();
    value = {
      name: "Atlas",
      version: "0.3.6",
      workspace: atlasPath(),
      healthy: !hasFailures(report.findings),
      findings: report.findings,
    };
  } else if (uri === "atlas://profiles") value = { profiles: await profiles() };
  else if (uri === "atlas://tickets") value = { tickets: await listTickets() };
  else if (uri === "atlas://handoffs")
    value = { handoffs: await listHandoffs() };
  else throw new Error(`Unknown Atlas resource: ${uri}`);
  return {
    uri,
    mimeType: "application/json",
    text: JSON.stringify(value, null, 2),
  };
}

function requiredArgument(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  if (typeof value !== "string" || !value)
    throw new Error(`${key} is required`);
  return value;
}

async function getPrompt(
  name: string,
  args: Record<string, unknown>,
): Promise<unknown> {
  if (name === "atlas_review_workspace")
    return {
      description: "Atlas workspace review",
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: "Run atlas_doctor and summarize only actionable findings. Do not change files.",
          },
        },
      ],
    };
  if (name === "atlas_review_ticket") {
    const ticket = requiredArgument(args, "ticket");
    return {
      description: `Review ${ticket}`,
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text: `Read the Atlas ticket ${ticket}, report PROVEN, NOT PROVEN, or BLOCKED, and propose exactly one next verified action.`,
          },
        },
      ],
    };
  }
  throw new Error(`Unknown Atlas prompt: ${name}`);
}

export async function handleAtlasMcpRequest(
  request: Request,
): Promise<Response | null> {
  if (request.method === "notifications/initialized") return null;
  if (request.method === "initialize")
    return {
      jsonrpc: "2.0",
      id: request.id,
      result: {
        protocolVersion: "2025-06-18",
        capabilities: { tools: {}, resources: {}, prompts: {} },
        serverInfo: { name: "atlas", version: "0.3.6" },
      },
    };
  if (request.method === "tools/list")
    return { jsonrpc: "2.0", id: request.id, result: { tools } };
  if (request.method === "resources/list")
    return { jsonrpc: "2.0", id: request.id, result: { resources } };
  if (request.method === "resources/read") {
    try {
      return {
        jsonrpc: "2.0",
        id: request.id,
        result: {
          contents: [await readResource(String(request.params?.uri ?? ""))],
        },
      };
    } catch (error) {
      return {
        jsonrpc: "2.0",
        id: request.id,
        error: {
          code: -32000,
          message: error instanceof Error ? error.message : String(error),
        },
      };
    }
  }
  if (request.method === "prompts/list")
    return { jsonrpc: "2.0", id: request.id, result: { prompts } };
  if (request.method === "prompts/get") {
    try {
      return {
        jsonrpc: "2.0",
        id: request.id,
        result: await getPrompt(
          String(request.params?.name ?? ""),
          (request.params?.arguments ?? {}) as Record<string, unknown>,
        ),
      };
    } catch (error) {
      return {
        jsonrpc: "2.0",
        id: request.id,
        error: {
          code: -32000,
          message: error instanceof Error ? error.message : String(error),
        },
      };
    }
  }
  if (request.method !== "tools/call")
    return {
      jsonrpc: "2.0",
      id: request.id,
      error: {
        code: -32601,
        message: `Unsupported MCP method: ${request.method ?? ""}`,
      },
    };
  const name = request.params?.name;
  if (typeof name !== "string" || !tools.some((tool) => tool.name === name))
    return {
      jsonrpc: "2.0",
      id: request.id,
      error: { code: -32602, message: "Unknown MCP tool" },
    };
  try {
    return {
      jsonrpc: "2.0",
      id: request.id,
      result: textResult(
        await callTool(
          name,
          (request.params?.arguments ?? {}) as Record<string, unknown>,
        ),
      ),
    };
  } catch (error) {
    return {
      jsonrpc: "2.0",
      id: request.id,
      error: {
        code: -32000,
        message: error instanceof Error ? error.message : String(error),
      },
    };
  }
}

export async function runAtlasMcpServer(): Promise<void> {
  let buffer = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", async (chunk: string) => {
    buffer += chunk;
    while (true) {
      const newline = buffer.indexOf("\n");
      if (newline < 0) return;
      const line = buffer.slice(0, newline).trim();
      buffer = buffer.slice(newline + 1);
      if (!line) continue;
      const request = JSON.parse(line) as Request;
      const response = await handleAtlasMcpRequest(request);
      if (!response) continue;
      process.stdout.write(`${JSON.stringify(response)}\n`);
    }
  });
  await new Promise<void>((resolve) => process.stdin.once("end", resolve));
}
