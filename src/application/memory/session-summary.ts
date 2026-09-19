import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Session, SessionEvent } from "../../domain/sessions/session.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { atlasPath, atlasRoot } from "../../paths.js";

const maxSummaryBytes = 12_000;

export type SessionSummaryResult = {
  summaryPath: string;
  summaryHash: string;
  summaryBytes: number;
};

function safeText(value: string, max = 800): string {
  return redactRuntimeText(value).replace(/\s+/g, " ").trim().slice(0, max);
}

function json(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

function eventText(
  events: SessionEvent[],
  types: string[],
  maxItems = 4,
): string[] {
  return events
    .filter((event) => types.includes(event.type))
    .map((event) => safeText(event.data))
    .filter(Boolean)
    .slice(0, maxItems);
}

function lastEvent(
  events: SessionEvent[],
  type: string,
): SessionEvent | undefined {
  return [...events].reverse().find((event) => event.type === type);
}

export function renderSessionSummary(input: {
  session: Session;
  events: SessionEvent[];
  changedFiles?: string[];
  exitCode?: number;
  nextAction?: string;
}): string {
  const { session, events } = input;
  const request =
    eventText(events, ["user_input", "resume_requested"], 1)[0] ??
    session.title;
  const outputs = eventText(events, ["provider_output", "text", "json"], 4);
  const errors = eventText(events, ["error", "provider_blocked"], 4);
  const evidence = events
    .filter((event) => event.type === "evidence")
    .map((event) => json(event.data))
    .filter((value): value is Record<string, unknown> => value !== null);
  const proven = evidence
    .filter((value) => value.result === "proven")
    .map((value) => String(value.criterion ?? "verified result"));
  const notProven = evidence
    .filter((value) => value.result !== "proven")
    .map((value) => String(value.criterion ?? value.result ?? "not proven"));
  const processExit = lastEvent(events, "process_exit");
  const exit =
    input.exitCode ??
    (processExit ? json(processExit.data)?.exitCode : undefined);
  const status =
    session.status === "completed" && exit === 0 ? "completed" : session.status;
  const nextAction =
    input.nextAction ??
    session.nextAction ??
    "Review the summary and verify the next action.";
  const lines = [
    "# Session Summary",
    "",
    `- Session: ${session.sessionId}`,
    `- Provider: ${session.provider}`,
    `- Ticket: ${session.ticketId ?? "none"}`,
    `- Profile: ${session.profile}`,
    `- Status: ${status}`,
    `- Working directory: ${safeText(session.workingDirectory, 240)}`,
    "",
    "## Objective",
    "",
    request || "No user objective was captured.",
    "",
    "## What happened",
    "",
    ...(outputs.length
      ? outputs.map((value) => `- ${value}`)
      : ["- No provider output was captured."]),
    "",
    "## Files changed",
    "",
    ...(input.changedFiles?.length
      ? input.changedFiles.map((value) => `- ${safeText(value, 240)}`)
      : ["- No changed-file evidence was recorded."]),
    "",
    "## Verification",
    "",
    ...(proven.length
      ? proven.map((value) => `- PROVEN: ${safeText(value)}`)
      : ["- No independently proven verification recorded."]),
    ...(notProven.length
      ? notProven.map((value) => `- NOT PROVEN: ${safeText(value)}`)
      : []),
    "",
    "## Problems and limitations",
    "",
    ...(errors.length
      ? errors.map((value) => `- ${value}`)
      : ["- None recorded."]),
    "",
    "## Next action",
    "",
    safeText(nextAction, 800),
    "",
    "## Retrieval",
    "",
    `- Detailed bounded events: atlas session events ${session.sessionId}`,
    `- Context bytes: ${session.contextBytes}`,
  ];
  let content = `${lines.join("\n")}\n`;
  if (Buffer.byteLength(content) > maxSummaryBytes)
    content = `${content.slice(0, maxSummaryBytes - 120)}\n\n- Summary truncated; detailed bounded events remain available by session id.\n`;
  return content;
}

export async function writeSessionSummary(input: {
  session: Session;
  events: SessionEvent[];
  changedFiles?: string[];
  exitCode?: number;
  nextAction?: string;
}): Promise<SessionSummaryResult> {
  const date =
    input.session.createdAt.slice(0, 10) ||
    new Date().toISOString().slice(0, 10);
  const directory = atlasPath("system", "sessions", "summaries");
  const file = path.join(directory, `${date}-${input.session.sessionId}.md`);
  await mkdir(directory, { recursive: true });
  const content = renderSessionSummary(input);
  await writeFile(file, content, "utf8");
  return {
    summaryPath: path.relative(atlasRoot(), file).split(path.sep).join("/"),
    summaryHash: createHash("sha256").update(content).digest("hex"),
    summaryBytes: Buffer.byteLength(content),
  };
}

/** Compatibility wrapper for older callers; governed closeout uses writeSessionSummary. */
export async function appendSessionSummary(input: {
  sessionId: string;
  provider: string;
  status: string;
  exitCode: number;
}): Promise<void> {
  const now = new Date().toISOString();
  const session: Session = {
    sessionId: input.sessionId,
    title: `${input.provider} session`,
    ticketId: null,
    handoffId: null,
    provider: input.provider,
    providerSessionId: null,
    parentSessionId: null,
    profile: `intercepted:${input.provider}`,
    profileIdentity: "",
    workingDirectory: atlasRoot(),
    status: input.status === "completed" ? "completed" : "failed",
    createdAt: now,
    updatedAt: now,
    resumeData: null,
    contextHash: null,
    contextBytes: 0,
    nextAction: "Review the session summary.",
    verificationStatus: "unknown",
    summaryPath: null,
    summaryHash: null,
    summaryBytes: 0,
    closeoutStatus: "pending",
    closeoutVersion: "1",
    closedAt: null,
  };
  await writeSessionSummary({ session, events: [], exitCode: input.exitCode });
}
