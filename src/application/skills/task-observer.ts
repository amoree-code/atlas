import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";

export type ObservationStatus = "observed" | "candidate" | "approved" | "promoted" | "discarded" | "rejected";
export type TaskObservation = {
  observationId: string;
  sourceSessionId: string;
  ticketId: string | null;
  profileId: string;
  signalType: "repeated-correction" | "repeated-procedure" | "explicit-decision" | "proven-verification";
  summary: string;
  evidenceRefs: string[];
  confidence: number;
  status: ObservationStatus;
  createdAt: string;
  reviewedAt: string | null;
};

const observationsFile = () => atlasPath("system", "skills", "observations.json");

async function load(): Promise<TaskObservation[]> {
  try { return JSON.parse(await readFile(observationsFile(), "utf8")) as TaskObservation[]; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}

async function save(items: TaskObservation[]): Promise<void> {
  await mkdir(path.dirname(observationsFile()), { recursive: true });
  await writeFile(observationsFile(), `${JSON.stringify(items.slice(-200), null, 2)}\n`, { mode: 0o600 });
}

function observationId(sessionId: string, signalType: string, summary: string): string {
  return `obs-${createHash("sha256").update(`${sessionId}:${signalType}:${summary}`).digest("hex").slice(0, 16)}`;
}

export async function observeSessionWithStore(store: Awaited<ReturnType<typeof openSessionStore>>, sessionId: string): Promise<TaskObservation[]> {
  const session = store.get(sessionId);
  if (!session) throw new Error(`Session not found: ${sessionId}`);
  if (session.status !== "completed") return [];
  const events = store.listEvents(sessionId);
    const proven = events.filter((event) => event.type === "evidence" && /"result"\s*:\s*"proven"/.test(event.data));
  if (!proven.length) return [];
    const outputs = events.filter((event) => ["provider_output", "text", "json"].includes(event.type)).map((event) => ({ id: event.eventId, text: redactRuntimeText(event.data).replace(/\s+/g, " ").trim() })).filter((event) => event.text.length > 12).slice(0, 80);
    const candidates: Array<{ signalType: TaskObservation["signalType"]; summary: string; refs: string[]; confidence: number }> = [];
    const decisions = outputs.filter((event) => /\bdecision\s*:/i.test(event.text));
    if (decisions.length) candidates.push({ signalType: "explicit-decision", summary: decisions[0].text.slice(0, 500), refs: decisions.slice(0, 4).map((event) => `event:${event.id}`), confidence: 0.9 });
    const counts = new Map<string, { count: number; refs: string[] }>();
    for (const event of outputs) {
      const normalized = event.text.toLocaleLowerCase();
      const current = counts.get(normalized) ?? { count: 0, refs: [] };
      current.count += 1; current.refs.push(`event:${event.id}`); counts.set(normalized, current);
    }
    const repeated = [...counts.entries()].find(([, value]) => value.count >= 2);
    if (repeated) candidates.push({ signalType: "repeated-procedure", summary: repeated[0].slice(0, 500), refs: repeated[1].refs.slice(0, 4), confidence: 0.8 });
    const corrections = outputs.filter((event) => /\b(correct|fix|instead|should use)\b/i.test(event.text));
    if (corrections.length) candidates.push({ signalType: "repeated-correction", summary: corrections[0].text.slice(0, 500), refs: corrections.slice(0, 4).map((event) => `event:${event.id}`), confidence: 0.7 });
    if (proven.length && outputs.some((event) => /verification|tests?\b|check(ed)?|passed/i.test(event.text))) candidates.push({ signalType: "proven-verification", summary: "The session contains independently recorded proven verification.", refs: proven.slice(0, 4).map((event) => `event:${event.eventId}`), confidence: 0.85 });
    const items = await load();
    const created: TaskObservation[] = [];
    for (const candidate of candidates.slice(0, 4)) {
      const id = observationId(sessionId, candidate.signalType, candidate.summary);
      if (items.some((item) => item.observationId === id)) continue;
      created.push({ observationId: id, sourceSessionId: sessionId, ticketId: session.ticketId, profileId: session.profile, signalType: candidate.signalType, summary: candidate.summary, evidenceRefs: candidate.refs, confidence: candidate.confidence, status: "observed", createdAt: new Date().toISOString(), reviewedAt: null });
    }
    if (created.length) await save([...items, ...created]);
  return created;
}

export async function observeSession(sessionId: string): Promise<TaskObservation[]> {
  const store = await openSessionStore();
  try { return await observeSessionWithStore(store, sessionId); }
  finally { store.close(); }
}

export async function listObservations(): Promise<TaskObservation[]> { return load(); }

export async function reviewObservation(observationIdValue: string, status: Exclude<ObservationStatus, "observed" | "candidate">): Promise<TaskObservation> {
  const items = await load(); const item = items.find((candidate) => candidate.observationId === observationIdValue);
  if (!item) throw new Error(`Observation not found: ${observationIdValue}`);
  item.status = status; item.reviewedAt = new Date().toISOString(); await save(items); return item;
}
