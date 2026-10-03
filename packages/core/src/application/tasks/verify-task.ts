import { execFile as execFileCallback } from "node:child_process";
import { readFile } from "node:fs/promises";
import { promisify } from "node:util";
import { atlasPath, PROJECTS_DIR, resolveWithin } from "../../paths.js";

const execFile = promisify(execFileCallback);

// Only commands whose first token is on this list are ever executed by the
// verifier. A task's `## Verification` section is prose with inline-backtick
// spans, so the allowlist keeps the verifier from running an arbitrary span
// that merely looks like a command.
const COMMAND_ALLOWLIST = new Set([
  "pnpm",
  "npm",
  "npx",
  "yarn",
  "node",
  "tsc",
  "atlas",
  "make",
  "bash",
  "sh",
  "pytest",
  "jest",
  "vitest",
  "biome",
]);

type VerificationCheck = {
  command: string;
  exitCode: number;
  ok: boolean;
};

export type VerificationOutcome = {
  id: string;
  passed: boolean;
  reason: string;
  checks: VerificationCheck[];
};

export type CommandRunner = (
  command: string,
  cwd: string,
) => Promise<{ exitCode: number }>;

const defaultRunner: CommandRunner = async (command, cwd) => {
  try {
    await execFile("bash", ["-lc", command], { cwd, timeout: 600_000 });
    return { exitCode: 0 };
  } catch (error) {
    const failure = error as { code?: number | string };
    const code =
      typeof failure.code === "number"
        ? failure.code
        : Number(failure.code) || 1;
    return { exitCode: code };
  }
};

/**
 * Pull runnable commands out of a task's verification declaration. A `verify:`
 * frontmatter field (string or comma-separated list) wins; otherwise the
 * inline-backtick spans of the `## Verification` section are used, filtered to
 * the command allowlist so prose spans are ignored.
 */
export function extractVerificationCommands(source: string): string[] {
  const frontmatter = source
    .match(/^verify:\s*(.+)$/m)?.[1]
    ?.trim()
    .replace(/^['"]|['"]$/g, "");
  if (frontmatter)
    return frontmatter
      .split(/\s*(?:,|&&|;)\s*/)
      .map((part) => part.trim())
      .filter(Boolean)
      .filter(isAllowedCommand);

  const section = source
    .match(/\n## Verification\n\n([\s\S]*?)(?=\n## |$)/)?.[1]
    ?.trim();
  if (!section) return [];
  const spans = [...section.matchAll(/`([^`]+)`/g)].map((match) =>
    match[1].trim(),
  );
  return spans.filter(isAllowedCommand);
}

function isAllowedCommand(command: string): boolean {
  const first = command.trim().split(/\s+/)[0];
  return COMMAND_ALLOWLIST.has(first);
}

/**
 * Independently verify a task by running the commands it declares. A task is
 * only verified when it declares at least one runnable check and every check
 * exits zero — the loop and `completeTask` never trust a self-reported
 * `state: done` on its own.
 */
export async function verifyTask(
  id: string,
  root = atlasPath(PROJECTS_DIR, "atlas", "tasks"),
  options: { cwd?: string; run?: CommandRunner } = {},
): Promise<VerificationOutcome> {
  const taskFile = resolveWithin(root, id, "task.md");
  const source = await readFile(taskFile, "utf8");
  const commands = extractVerificationCommands(source);
  if (commands.length === 0)
    return {
      id,
      passed: false,
      reason:
        "no runnable verification commands declared; cannot self-certify done",
      checks: [],
    };
  const run = options.run ?? defaultRunner;
  const cwd = options.cwd ?? atlasPath("engine");
  const checks: VerificationCheck[] = [];
  for (const command of commands) {
    const { exitCode } = await run(command, cwd);
    checks.push({ command, exitCode, ok: exitCode === 0 });
  }
  const passed = checks.every((check) => check.ok);
  return {
    id,
    passed,
    reason: passed
      ? "all verification checks passed"
      : `verification failed: ${checks
          .filter((check) => !check.ok)
          .map((check) => check.command)
          .join(", ")}`,
    checks,
  };
}
