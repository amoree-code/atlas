import { execFile as execFileCallback } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import {
  compactHandoff,
  type Handoff,
  validateHandoff,
} from "../../domain/sessions/handoff.js";
import {
  openSessionStore,
  type SessionStore,
} from "../../infrastructure/persistence/session-store.js";
import { atlasPath, engineRoot, resolveWithin } from "../../paths.js";

const execFile = promisify(execFileCallback);
const maxContentBytes = 16_000;

export type Task = {
  id: string;
  title: string;
  state: string;
  goal: string;
  objective: string;
  body: string;
  updatedAt: string;
};

export async function createHandoff(input: {
  taskId?: string;
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
  const task = input.taskId ? await getTask(input.taskId) : null;
  const store = await openSessionStore();
  try {
    return await createHandoffWithStore(store, { ...input, task });
  } finally {
    store.close();
  }
}

export async function createHandoffWithStore(
  store: SessionStore,
  input: {
    taskId?: string;
    sessionId?: string;
    profileId?: string;
    nextAction?: string;
    provider?: string;
    sourceSummaryPath?: string | null;
    changedFiles?: string[];
    verification?: string[];
    notProven?: string[];
    blocked?: string[];
    task?: Task | null;
  },
): Promise<Handoff> {
  const task =
    input.task === undefined && input.taskId
      ? await getTask(input.taskId)
      : (input.task ?? null);
  const session = input.sessionId ? store.get(input.sessionId) : null;
  if (input.sessionId && !session)
    throw new Error(`Session not found: ${input.sessionId}`);
  const commit = await currentCommit();
  const now = new Date().toISOString();
  const content = (task?.body ?? "").slice(0, maxContentBytes);
  const handoff = validateHandoff({
    handoffId: `handoff-${randomUUID()}`,
    taskId: task?.id ?? session?.taskId ?? null,
    title: task?.title ?? session?.title ?? "Atlas session handoff",
    objective:
      task?.objective ??
      "Continue the selected Atlas session with bounded context.",
    state: task?.state ?? session?.status ?? "paused",
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
    contextManifest: {
      bytes: session?.contextBytes ?? 0,
      hash: session?.contextHash ?? null,
      mode: "bounded",
    },
    nextAction:
      input.nextAction ??
      session?.nextAction ??
      "Verify the current state before changing files.",
    sourceSummaryPath: input.sourceSummaryPath ?? null,
    content,
    contentBytes: Buffer.byteLength(content),
    createdAt: now,
    updatedAt: now,
  });
  store.saveHandoff(handoff);
  if (session)
    store.updateHandoff(
      session.sessionId,
      handoff.handoffId,
      handoff.nextAction,
    );
  return handoff;
}

export async function getHandoff(
  handoffId: string,
  maxBytes = 8_000,
): Promise<Record<string, unknown>> {
  const store = await openSessionStore();
  try {
    const handoff = store.getHandoff(handoffId);
    if (!handoff) throw new Error(`Handoff not found: ${handoffId}`);
    return {
      ...handoff,
      compactContext: compactHandoff(validateHandoff(handoff), maxBytes),
    };
  } finally {
    store.close();
  }
}

export async function listHandoffs(
  taskId?: string,
): Promise<Array<Record<string, unknown>>> {
  const store = await openSessionStore();
  try {
    return store
      .listHandoffs(taskId)
      .map(({ content: _content, ...handoff }) => handoff);
  } finally {
    store.close();
  }
}

export async function getTask(id: string): Promise<Task> {
  const tasksRoot = atlasPath("projects", "atlas", "tasks");
  const candidates = [
    resolveWithin(tasksRoot, id, "task.md"),
    resolveWithin(tasksRoot, "archive", "Atlas", id, "task.md"),
  ];
  let file = "";
  for (const candidate of candidates) {
    try {
      file = await readFile(candidate, "utf8");
      break;
    } catch {
      /* try the archived authority */
    }
  }
  if (!file) throw new Error(`Task not found: ${id}`);
  const end = file.indexOf("\n---", 4);
  const frontmatter = file
    .slice(0, end < 0 ? 0 : end)
    .split("\n")
    .slice(1);
  const fields = Object.fromEntries(
    frontmatter
      .filter((line) => /^[\w-]+:/.test(line))
      .map((line) => {
        const index = line.indexOf(":");
        return [line.slice(0, index), line.slice(index + 1).trim()];
      }),
  );
  const body = file.slice(end < 0 ? 0 : end + 5);
  const objective =
    body.match(/(?:^|\n)## Objective\n\n([\s\S]*?)(?=\n## |$)/)?.[1]?.trim() ??
    "";
  return {
    id: fields.id ?? id,
    title: fields.title ?? id,
    state: fields.state ?? "unknown",
    goal: objective || fields.goal || "",
    objective: objective || fields.requirement || fields.goal || "",
    body,
    updatedAt: fields.updated ?? fields.updated_at ?? "",
  };
}

async function currentCommit(): Promise<string | null> {
  try {
    return (
      (
        await execFile("git", ["-C", engineRoot(), "rev-parse", "HEAD"])
      ).stdout.trim() || null
    );
  } catch {
    return null;
  }
}

export function handoffContextHash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}
