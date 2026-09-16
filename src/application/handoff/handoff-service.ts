import { randomUUID, createHash } from "node:crypto";
import { execFile as execFileCallback } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import { atlasPath, engineRoot, resolveWithin } from "../../paths.js";
import { compactHandoff, validateHandoff, type Handoff } from "../../domain/sessions/handoff.js";
import { openSessionStore, type SessionStore } from "../../infrastructure/persistence/session-store.js";

const execFile = promisify(execFileCallback);
const maxContentBytes = 16_000;

export type Ticket = { id: string; title: string; state: string; goal: string; objective: string; body: string; updatedAt: string };

export async function createHandoff(input: {
  ticketId?: string;
  sessionId?: string;
  profileId?: string;
  nextAction?: string;
  provider?: string;
  sourceSummaryPath?: string | null;
  changedFiles?: string[];
  verification?: string[];
  notProven?: string[];
  blocked?: string[];
}): Promise<Handoff> {
  const ticket = input.ticketId ? await getTicket(input.ticketId) : null;
  const store = await openSessionStore();
  try { return await createHandoffWithStore(store, { ...input, ticket }); }
  finally { store.close(); }
}

export async function createHandoffWithStore(store: SessionStore, input: {
  ticketId?: string;
  sessionId?: string;
  profileId?: string;
  nextAction?: string;
  provider?: string;
  sourceSummaryPath?: string | null;
  changedFiles?: string[];
  verification?: string[];
  notProven?: string[];
  blocked?: string[];
  ticket?: Ticket | null;
}): Promise<Handoff> {
  const ticket = input.ticket === undefined && input.ticketId ? await getTicket(input.ticketId) : input.ticket ?? null;
  const session = input.sessionId ? store.get(input.sessionId) : null;
  if (input.sessionId && !session) throw new Error(`Session not found: ${input.sessionId}`);
  const commit = await currentCommit();
  const now = new Date().toISOString();
  const content = (ticket?.body ?? "").slice(0, maxContentBytes);
  const handoff = validateHandoff({
    handoffId: `handoff-${randomUUID()}`,
    ticketId: ticket?.id ?? session?.ticketId ?? null,
    title: ticket?.title ?? session?.title ?? "Atlas session handoff",
    objective: ticket?.objective ?? "Continue the selected Atlas session with bounded context.",
    state: ticket?.state ?? session?.status ?? "paused",
    profileId: input.profileId ?? session?.profile ?? "",
    profileIdentity: session?.profileIdentity ?? "",
    sourceSessionId: session?.sessionId ?? null,
    provider: input.provider ?? session?.provider ?? "",
    parentSessionId: session?.parentSessionId ?? null,
    decisions: [],
    changedFiles: input.changedFiles ?? [],
    commit,
    verification: input.verification ?? [],
    notProven: input.notProven ?? [],
    blocked: input.blocked ?? [],
    permissions: { profile: input.profileId ?? session?.profile ?? null },
    contextManifest: { bytes: session?.contextBytes ?? 0, hash: session?.contextHash ?? null, mode: "bounded" },
    nextAction: input.nextAction ?? session?.nextAction ?? "Verify the current state before changing files.",
    sourceSummaryPath: input.sourceSummaryPath ?? null,
    content,
    contentBytes: Buffer.byteLength(content),
    createdAt: now,
    updatedAt: now,
  });
  store.saveHandoff(handoff);
  if (session) store.updateHandoff(session.sessionId, handoff.handoffId, handoff.nextAction);
  return handoff;
}

export async function getHandoff(handoffId: string, maxBytes = 8_000): Promise<Record<string, unknown>> {
  const store = await openSessionStore();
  try {
    const handoff = store.getHandoff(handoffId);
    if (!handoff) throw new Error(`Handoff not found: ${handoffId}`);
    return { ...handoff, compactContext: compactHandoff(validateHandoff(handoff), maxBytes) };
  } finally { store.close(); }
}

export async function listHandoffs(ticketId?: string): Promise<Array<Record<string, unknown>>> {
  const store = await openSessionStore();
  try { return store.listHandoffs(ticketId).map(({ content: _content, ...handoff }) => handoff); }
  finally { store.close(); }
}

export async function getTicket(id: string): Promise<Ticket> {
  const ticketsRoot = atlasPath("projects", "atlas", "tickets");
  const candidates = [
    resolveWithin(ticketsRoot, id, "task.md"),
    resolveWithin(ticketsRoot, "archive", "Atlas", id, "task.md"),
  ];
  let file = "";
  for (const candidate of candidates) {
    try { file = await readFile(candidate, "utf8"); break; } catch { /* try the archived authority */ }
  }
  if (!file) throw new Error(`Ticket not found: ${id}`);
  const end = file.indexOf("\n---", 4);
  const frontmatter = file.slice(0, end < 0 ? 0 : end).split("\n").slice(1);
  const fields = Object.fromEntries(frontmatter.filter((line) => /^[\w-]+:/.test(line)).map((line) => {
    const index = line.indexOf(":"); return [line.slice(0, index), line.slice(index + 1).trim()];
  }));
  return {
    id: fields.id ?? id, title: fields.title ?? id, state: fields.state ?? "unknown", goal: fields.goal ?? "",
    objective: fields.requirement ?? fields.goal ?? "", body: file.slice(end < 0 ? 0 : end + 5), updatedAt: fields.updated_at ?? "",
  };
}

async function currentCommit(): Promise<string | null> {
  try { return (await execFile("git", ["-C", engineRoot(), "rev-parse", "HEAD"])).stdout.trim() || null; }
  catch { return null; }
}

export function handoffContextHash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
