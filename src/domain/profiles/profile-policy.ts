import path from "node:path";
import type { Profile } from "./profile.js";

const providerCommand: Record<Profile["provider"], string> = {
  claude: "claude",
  codex: "codex",
  gemini: "gemini",
  antigravity: "agy",
  hermes: "hermes",
  kilo: "kilo",
  kimi: "kimi",
};

export type ExecutionPolicy = {
  providerCommand: string;
  writePolicy: Profile["writePolicy"];
  allowedPaths: string[];
};

export function executionPolicy(
  profile: Profile,
  cwd: string,
): ExecutionPolicy {
  const command = providerCommand[profile.provider];
  if (
    profile.allowedCommands.length &&
    !profile.allowedCommands.some(
      (allowed) =>
        command === allowed ||
        path.basename(command) === path.basename(allowed),
    )
  ) {
    throw new Error(`Policy denied provider command: ${command}`);
  }
  if (
    profile.writePolicy === "allowed-paths" &&
    profile.allowedPaths.length === 0
  ) {
    throw new Error("Policy denied writable run without allowed paths");
  }
  if (!path.isAbsolute(cwd))
    throw new Error("Policy denied non-absolute working directory");
  return {
    providerCommand: command,
    writePolicy: profile.writePolicy,
    allowedPaths: profile.allowedPaths,
  };
}
