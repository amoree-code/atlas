import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Session, SessionEvent } from "../../domain/sessions/session.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { atlasPath, atlasRoot } from "../../paths.js";
import { findGitRoot } from "../context/project-resolution.js";
import type { ModelNarrative } from "./model-narrative.js";

// Same fallback title stamped on a session with no explicit title (see
// daily-narrative.ts) — never meaningful content on its own.
const GENERIC_TITLE =
  /^(claude|codex|hermes|kimi|gemini|copilot|kilo|antigravity|openhands) session$/i;

function safeText(value: string, max = 400): string {
  return redactRuntimeText(value).replace(/\s+/g, " ").trim().slice(0, max);
}

function isGenericContent(text: string | null | undefined): boolean {
  const trimmed = (text ?? "").trim();
  return trimmed.length === 0 || GENERIC_TITLE.test(trimmed);
}

/**
 * One human-readable Markdown file per session under personal/brain-dump/,
 * separate from the machine-oriented system/sessions/summaries/ dump. Prefers
 * the cheap model narrative (see model-narrative.ts) and falls back to the
 * same deterministic heuristics as daily-narrative.ts when it is unavailable.
 *
 * Skipped for the same low-value case daily-narrative.ts skips: a generic
 * title with no real (git) project behind it — nothing a human would want to
 * read later.
 */
export async function writeBrainDump(input: {
  session: Session;
  events: SessionEvent[];
  changedFiles: string[];
  exitCode?: number;
  nextAction?: string;
  narrative?: ModelNarrative | null;
}): Promise<{ brainDumpPath: string } | null> {
  const { session, events, narrative, changedFiles } = input;

  const workLog =
    narrative?.workLog ??
    (() => {
      const objectiveEvent = events.find(
        (event) =>
          event.type === "user_input" || event.type === "resume_requested",
      );
      return safeText(objectiveEvent?.data ?? session.title, 200);
    })();

  const hasRealProject = findGitRoot(session.workingDirectory) !== null;
  if (isGenericContent(workLog) && !hasRealProject) return null;

  const decision =
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

  const problem =
    narrative?.problem ??
    events
      .filter(
        (event) => event.type === "error" || event.type === "provider_blocked",
      )
      .map((event) => safeText(event.data, 500))[0];

  const nextAction = narrative?.next ?? input.nextAction ?? session.nextAction;
  const hasNextAction =
    nextAction &&
    nextAction !== "Review the summary and verify the next action.";

  const time =
    session.createdAt.slice(11, 16) || new Date().toISOString().slice(11, 16);
  const date =
    session.createdAt.slice(0, 10) || new Date().toISOString().slice(0, 10);
  const project =
    path.basename(session.workingDirectory) || session.workingDirectory;
  const status =
    session.status === "completed" && (input.exitCode ?? 0) === 0
      ? "completed"
      : "failed";
  const title = isGenericContent(workLog) ? project : workLog;

  const lines = [
    `# ${title}`,
    "",
    `- Date: ${date} ${time}`,
    `- Provider: ${session.provider}`,
    `- Project: ${project}`,
    `- Status: ${status}`,
    "",
    "## What happened",
    "",
    workLog || "No objective was captured.",
    ...(decision ? ["", "## Decision", "", decision] : []),
    ...(problem ? ["", "## Problem", "", problem] : []),
    ...(changedFiles.length
      ? [
          "",
          "## Files changed",
          "",
          ...changedFiles.map((f) => `- ${safeText(f, 240)}`),
        ]
      : []),
    ...(hasNextAction
      ? ["", "## Next", "", safeText(nextAction as string, 300)]
      : []),
    "",
    "---",
    "",
    `Session id: ${session.sessionId} · Raw events: \`atlas session events ${session.sessionId}\``,
  ];

  const directory = atlasPath("personal", "brain-dump");
  const file = path.join(directory, `${date}-${session.sessionId}.md`);
  await mkdir(directory, { recursive: true });
  await writeFile(file, `${lines.join("\n")}\n`, "utf8");
  return {
    brainDumpPath: path.relative(atlasRoot(), file).split(path.sep).join("/"),
  };
}
