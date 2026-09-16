import { execFile as execFileCallback } from "node:child_process";
import { promisify } from "node:util";
import type { SessionEvent } from "../../domain/sessions/session.js";
import { createHandoffWithStore } from "../handoff/handoff-service.js";
import { openSessionStore, type SessionStore } from "../../infrastructure/persistence/session-store.js";
import { writeSessionSummary, type SessionSummaryResult } from "./session-summary.js";
import { observeSessionWithStore } from "../skills/task-observer.js";

const execFile = promisify(execFileCallback);

export type SessionCloseoutResult = SessionSummaryResult & { handoffId: string | null; closeoutStatus: "completed" | "failed" };

async function changedFiles(workingDirectory: string): Promise<string[]> {
  try {
    const result = await execFile("git", ["-C", workingDirectory, "status", "--short"], { timeout: 1_000, maxBuffer: 16_384 });
    return result.stdout.split("\n").map((line) => line.trim()).filter(Boolean).slice(0, 100);
  } catch { return []; }
}

function json(data: string): Record<string, unknown> | null {
  try {
    const value = JSON.parse(data);
    return value && typeof value === "object" ? value as Record<string, unknown> : null;
  } catch { return null; }
}

function lastEvent(events: SessionEvent[], type: string): SessionEvent | undefined {
  return [...events].reverse().find((event) => event.type === type);
}

function evidence(events: SessionEvent[], result: "proven" | "notProven" | "blocked"): string[] {
  return events.filter((event) => event.type === "evidence" || event.type === "provider_blocked").map((event) => {
    const value = json(event.data);
    if (event.type === "provider_blocked") return result === "blocked" ? String(value?.reason ?? event.data) : null;
    const proven = value?.result === "proven";
    if (result === "proven" && proven) return String(value?.criterion ?? "verified result");
    if (result === "notProven" && !proven) return String(value?.criterion ?? value?.result ?? "not proven");
    return null;
  }).filter((value): value is string => Boolean(value)).slice(0, 12);
}

export async function finalizeSession(store: SessionStore, sessionId: string, input: { exitCode?: number; nextAction?: string } = {}): Promise<SessionCloseoutResult> {
  const session = store.get(sessionId);
  if (!session) throw new Error(`Session not found: ${sessionId}`);
  const events = store.listEvents(sessionId);
  const exitEvent = lastEvent(events, "process_exit");
  const exitCode = input.exitCode ?? (exitEvent ? Number(json(exitEvent.data)?.exitCode ?? 1) : session.status === "completed" ? 0 : 1);
  const closeoutStatus = session.status === "completed" && exitCode === 0 ? "completed" : "failed";
  const files = await changedFiles(session.workingDirectory);
  const summary = await writeSessionSummary({ session, events, changedFiles: files, exitCode, nextAction: input.nextAction });
  let handoffId = session.handoffId;
  const enoughEvidence = Boolean(session.ticketId || (closeoutStatus === "completed" && events.some((event) => ["user_input", "provider_output", "text", "json"].includes(event.type))));
  if (!handoffId && enoughEvidence) {
    try {
      const handoff = await createHandoffWithStore(store, {
        sessionId, ticketId: session.ticketId ?? undefined, nextAction: input.nextAction,
        sourceSummaryPath: summary.summaryPath, changedFiles: files,
        verification: evidence(events, "proven"), notProven: evidence(events, "notProven"), blocked: evidence(events, "blocked"),
      });
      handoffId = handoff.handoffId;
    } catch (error) {
      store.appendEvent(sessionId, "closeout_warning", error instanceof Error ? error.message : String(error));
    }
  }
  const closedAt = new Date().toISOString();
  store.updateCloseout(sessionId, { ...summary, closeoutStatus, closedAt });
  try { await observeSessionWithStore(store, sessionId); } catch (error) { store.appendEvent(sessionId, "closeout_warning", error instanceof Error ? error.message : String(error)); }
  if (!store.listEvents(sessionId).some((event) => event.type === "session_summary")) {
    store.appendEvent(sessionId, "session_summary", JSON.stringify({ ...summary, handoffId, closeoutStatus, closedAt }));
  }
  return { ...summary, handoffId, closeoutStatus };
}

export async function finalizeSessionById(sessionId: string, input: { exitCode?: number; nextAction?: string } = {}): Promise<SessionCloseoutResult> {
  const store = await openSessionStore();
  try { return await finalizeSession(store, sessionId, input); }
  finally { store.close(); }
}
