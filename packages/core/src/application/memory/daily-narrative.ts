import { randomUUID } from "node:crypto";
import {
  link,
  mkdir,
  open,
  readFile,
  rename,
  stat,
  unlink,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { redactRuntimeText } from "../../domain/redaction/redaction.js";
import type { Session, SessionEvent } from "../../domain/sessions/session.js";
import { DAILY_DIR, oceanPath } from "../../paths.js";
import { findGitRoot } from "../context/project-resolution.js";
import type { TaskObservation } from "../skills/task-observer.js";
import type { ModelNarrative } from "./model-narrative.js";

const dailyTemplate = (date: string): string =>
  `# Daily — ${date}\n\n## Focus\n\n## Work log\n\n## Decisions\n\n## Problems\n\n## Next\n\n## Observations\n`;

// The literal fallback title stamped on a session with no explicit title
// (see run request construction) — never meaningful content on its own.
const GENERIC_TITLE = /^claude session$/i;

function safeText(value: string, max = 240): string {
  return redactRuntimeText(value).replace(/\s+/g, " ").trim().slice(0, max);
}

function isGenericContent(text: string | null | undefined): boolean {
  const trimmed = (text ?? "").trim();
  return trimmed.length === 0 || GENERIC_TITLE.test(trimmed);
}

function insertUnderHeading(
  content: string,
  heading: string,
  line: string,
): string {
  const marker = `${heading}\n`;
  const index = content.indexOf(marker);
  if (index < 0) return `${content.trimEnd()}\n\n${heading}\n${line}\n`;
  const insertAt = index + marker.length;
  return `${content.slice(0, insertAt)}${line}\n${content.slice(insertAt)}`;
}

// Two sessions closing out at once each read the daily file, edit it in memory and write it
// back; without a lock the later write drops the earlier one's lines (T-257). The lock is a
// file created with "wx" beside the daily file, holding the owner's pid — the same pattern
// as the scheduler lease. A lock whose owner is dead is stale and taken over.
const LOCK_WAIT_MS = 10_000;
const LOCK_RETRY_MS = 20;
// The owner writes its pid right after creating the lock; an empty lock older than this
// belongs to a writer that died in between.
const EMPTY_LOCK_STALE_MS = 5_000;

function processIsAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return (error as NodeJS.ErrnoException).code === "EPERM";
  }
}

async function lockIsStale(lock: string): Promise<string | null> {
  const contents = await readFile(lock, "utf8").catch(() => null);
  if (contents === null) return null;
  const owner = Number.parseInt(contents.trim(), 10);
  if (Number.isInteger(owner) && owner > 0)
    return processIsAlive(owner) ? null : contents;
  const age = await stat(lock)
    .then((info) => Date.now() - info.mtimeMs)
    .catch(() => 0);
  return age > EMPTY_LOCK_STALE_MS ? contents : null;
}

// Moves a stale lock aside atomically. If another writer replaced it with a live lock in
// between, the moved file is not the stale one: put it back (link never overwrites).
async function takeOverStaleLock(lock: string, stale: string): Promise<void> {
  const aside = `${lock}.stale-${process.pid}-${randomUUID()}`;
  try {
    await rename(lock, aside);
  } catch {
    return;
  }
  const moved = await readFile(aside, "utf8").catch(() => stale);
  if (moved !== stale) await link(aside, lock).catch(() => undefined);
  await unlink(aside).catch(() => undefined);
}

async function acquireDailyLock(lock: string): Promise<void> {
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    try {
      const handle = await open(lock, "wx");
      try {
        await handle.writeFile(`${process.pid}\n`);
      } finally {
        await handle.close();
      }
      return;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
    const stale = await lockIsStale(lock);
    if (stale !== null) {
      await takeOverStaleLock(lock, stale);
      continue;
    }
    if (Date.now() > deadline)
      throw new Error(
        `Daily log lock ${lock} still held after ${LOCK_WAIT_MS} ms; entry not written`,
      );
    await new Promise((resolve) => setTimeout(resolve, LOCK_RETRY_MS));
  }
}

// Read-modify-write of today's daily file under the lock, written atomically (temp file +
// rename) so a reader never sees a half-written file.
async function updateDailyFile(
  update: (content: string) => string,
): Promise<void> {
  const date = new Date().toISOString().slice(0, 10);
  const directory = oceanPath(DAILY_DIR);
  const file = path.join(directory, `${date}.md`);
  const lock = `${file}.lock`;
  await mkdir(directory, { recursive: true });
  await acquireDailyLock(lock);
  try {
    let content: string;
    try {
      content = await readFile(file, "utf8");
    } catch {
      content = dailyTemplate(date);
    }
    const next = update(content);
    const temporary = `${file}.ocean-tmp-${process.pid}-${randomUUID()}`;
    await writeFile(temporary, next, "utf8");
    await rename(temporary, file);
  } finally {
    await unlink(lock).catch(() => undefined);
  }
}

/**
 * Human-readable narrative entry appended to today's
 * brain/01-daily/YYYY-MM-DD.md at session closeout. A field from `narrative`
 * (produced by a cheap model call — see model-narrative.ts) is used verbatim
 * when present; any field it omits (including when the model call was
 * skipped or failed entirely) falls back to the deterministic heuristic
 * below, so this never depends on the model call succeeding.
 */
export async function appendDailyNarrative(input: {
  session: Session;
  events: SessionEvent[];
  exitCode?: number;
  nextAction?: string;
  narrative?: ModelNarrative | null;
}): Promise<void> {
  const { session, events, narrative } = input;
  const inserts: Array<[heading: string, line: string]> = [];
  const time = new Date().toISOString().slice(11, 16);
  const project =
    path.basename(session.workingDirectory) || session.workingDirectory;
  const status =
    session.status === "completed" && (input.exitCode ?? 0) === 0
      ? "completed"
      : "failed";

  const workLog =
    narrative?.workLog ??
    (() => {
      const objectiveEvent = events.find(
        (event) =>
          event.type === "user_input" || event.type === "resume_requested",
      );
      return safeText(objectiveEvent?.data ?? session.title, 160);
    })();

  // Skip the doubly-useless case: no real content beyond the generic
  // placeholder title, AND no real project (root/home session, no git repo)
  // to give the entry any meaning. A generic title in a real project, or
  // real content with no project, still gets logged.
  const hasRealProject = findGitRoot(session.workingDirectory) !== null;
  const skipWorkLog = isGenericContent(workLog) && !hasRealProject;
  if (!skipWorkLog) {
    inserts.push([
      "## Work log",
      `- ${time} ${session.provider} session in ${project}: ${workLog} — ${status}`,
    ]);
  }

  const decisionLine =
    narrative?.decision ??
    events
      .filter(
        (event) =>
          event.type === "provider_output" ||
          event.type === "text" ||
          event.type === "json",
      )
      .map((event) => safeText(event.data, 500))
      .find((text) => /\bdecision\s*:/i.test(text));
  if (decisionLine) inserts.push(["## Decisions", `- ${decisionLine}`]);

  const problemLine =
    narrative?.problem ??
    events
      .filter(
        (event) => event.type === "error" || event.type === "provider_blocked",
      )
      .map((event) => safeText(event.data, 500))[0];
  if (problemLine) inserts.push(["## Problems", `- ${problemLine}`]);

  const nextAction = narrative?.next ?? input.nextAction ?? session.nextAction;
  if (
    nextAction &&
    nextAction !== "Review the summary and verify the next action."
  ) {
    inserts.push(["## Next", `- [${project}] ${safeText(nextAction, 240)}`]);
  }

  await updateDailyFile((content) =>
    inserts.reduce(
      (next, [heading, line]) => insertUnderHeading(next, heading, line),
      content,
    ),
  );
}

/**
 * Appends newly detected observations (corrections, repeated procedures,
 * explicit decisions, proven verifications — see task-observer.ts) to
 * today's brain/01-daily/YYYY-MM-DD.md, so they surface next to the
 * session narrative instead of sitting only in system/skills/observations.json.
 */
export async function appendObservations(
  session: Session,
  observations: TaskObservation[],
): Promise<void> {
  if (!observations.length) return;
  const project =
    path.basename(session.workingDirectory) || session.workingDirectory;
  await updateDailyFile((content) =>
    observations.reduce(
      (next, observation) =>
        insertUnderHeading(
          next,
          "## Observations",
          `- [${observation.signalType}] ${safeText(observation.summary, 300)} _(${project}, confidence ${observation.confidence})_`,
        ),
      content,
    ),
  );
}
