import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { resolveProject } from "../context/project-resolution.js";
import { buildAtlasBootstrap } from "../context/resource-injection.js";

// The documented Claude Code SessionStart hook contract on this machine (verified against
// the live ~/.claude/settings.json hook entries, e.g. the existing ai-guard-push PreToolUse
// hook): a hook reads a small JSON payload on stdin and may print
// {"hookSpecificOutput": {"hookEventName": "...", "additionalContext": "..."}} on stdout.
// additionalContext is the only thing Atlas adds — never file content, never a transcript.
export type ClaudeSessionStartPayload = {
  cwd?: string;
  session_id?: string;
  hook_event_name?: string;
};

export type ClaudeSessionStartResult = {
  hookSpecificOutput: {
    hookEventName: "SessionStart";
    additionalContext: string;
  };
};

const MAX_STDIN_BYTES = 65_536;

export async function readBoundedStdin(
  stream: NodeJS.ReadStream = process.stdin,
  maxBytes = MAX_STDIN_BYTES,
): Promise<string> {
  if (stream.isTTY) return "";
  const chunks: Buffer[] = [];
  let bytes = 0;
  for await (const chunk of stream) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    bytes += buffer.length;
    if (bytes > maxBytes)
      throw new Error(
        `Session-start hook payload exceeds the ${maxBytes}-byte bound`,
      );
    chunks.push(buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

export async function claudeSessionStartHook(
  payload: ClaudeSessionStartPayload,
): Promise<ClaudeSessionStartResult> {
  const cwd = payload.cwd ?? process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
  const project = await resolveProject(cwd);
  const bootstrap = buildAtlasBootstrap(project);
  return {
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: bootstrap.content,
    },
  };
}

export type ClaudeNativeHookStatus = {
  scriptPath: string;
  scriptInstalled: boolean;
  settingsPath: string;
  registered: boolean;
};

// Read-only status check: does the hook script exist on disk, and is it actually registered
// under hooks.SessionStart in the live Claude Code settings? Registration is never done
// automatically here (see ../../../../system/integrations/claude-code/hooks/atlas-session-bootstrap
// for the manual-copy convention) — this only reports the truth, it never assumes it.
export async function claudeNativeHookStatus(
  homeDir = os.homedir(),
): Promise<ClaudeNativeHookStatus> {
  const scriptPath = path.join(
    homeDir,
    "atlas",
    "system",
    "integrations",
    "claude-code",
    "hooks",
    "atlas-session-bootstrap",
  );
  const settingsPath = path.join(homeDir, ".claude", "settings.json");
  let scriptInstalled = false;
  try {
    await readFile(scriptPath, "utf8");
    scriptInstalled = true;
  } catch {
    scriptInstalled = false;
  }
  let registered = false;
  try {
    const settings = JSON.parse(await readFile(settingsPath, "utf8")) as {
      hooks?: { SessionStart?: Array<{ hooks?: Array<{ command?: string }> }> };
    };
    const entries = settings.hooks?.SessionStart ?? [];
    registered = entries.some((entry) =>
      (entry.hooks ?? []).some((hook) =>
        hook.command?.includes("atlas-session-bootstrap"),
      ),
    );
  } catch {
    registered = false;
  }
  return { scriptPath, scriptInstalled, settingsPath, registered };
}
