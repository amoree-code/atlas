import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Session, SessionEvent } from "../../domain/sessions/session.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { atlasPath } from "../../paths.js";
import type { ModelNarrative } from "./model-narrative.js";

const dailyTemplate = (date: string): string =>
  `# Daily — ${date}\n\n## Focus\n\n## Work log\n\n## Decisions\n\n## Problems\n\n## Next\n`;

function safeText(value: string, max = 240): string {
  return redactRuntimeText(value).replace(/\s+/g, " ").trim().slice(0, max);
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

/**
 * Human-readable narrative entry appended to today's
 * personal/daily/YYYY-MM-DD.md at session closeout. A field from `narrative`
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
  const date = new Date().toISOString().slice(0, 10);
  const directory = atlasPath("personal", "daily");
  const file = path.join(directory, `${date}.md`);
  await mkdir(directory, { recursive: true });

  let content: string;
  try {
    content = await readFile(file, "utf8");
  } catch {
    content = dailyTemplate(date);
  }

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
  content = insertUnderHeading(
    content,
    "## Work log",
    `- ${time} ${session.provider} session in ${project}: ${workLog} — ${status}`,
  );

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
  if (decisionLine)
    content = insertUnderHeading(content, "## Decisions", `- ${decisionLine}`);

  const problemLine =
    narrative?.problem ??
    events
      .filter(
        (event) => event.type === "error" || event.type === "provider_blocked",
      )
      .map((event) => safeText(event.data, 500))[0];
  if (problemLine)
    content = insertUnderHeading(content, "## Problems", `- ${problemLine}`);

  const nextAction = narrative?.next ?? input.nextAction ?? session.nextAction;
  if (
    nextAction &&
    nextAction !== "Review the summary and verify the next action."
  ) {
    content = insertUnderHeading(
      content,
      "## Next",
      `- [${project}] ${safeText(nextAction, 240)}`,
    );
  }

  await writeFile(file, content, "utf8");
}
