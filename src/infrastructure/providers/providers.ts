import path from "node:path";
import { runHeadless, type HeadlessResult, type RuntimeEvent } from "../process/cli-process.js";

export type HeadlessProvider = "claude" | "codex" | "gemini" | "antigravity";

export type ProviderRequest = {
  provider: HeadlessProvider;
  prompt: string;
  cwd: string;
  resumeId?: string;
  timeoutMs?: number;
  maxOutputBytes?: number;
  onEvent?: (event: RuntimeEvent) => void;
};

export function buildProviderInvocation(request: ProviderRequest): { command: string; args: string[] } {
  const command = request.provider === "antigravity" ? "agy" : request.provider;
  const args = request.provider === "claude"
    ? [...(request.resumeId ? ["--resume", request.resumeId] : []), "-p", request.prompt, "--verbose", "--output-format", "stream-json"]
    : request.provider === "codex"
      ? ["exec", "--json", request.prompt]
      : request.provider === "gemini"
        ? ["--prompt", request.prompt, "--output-format", "stream-json"]
        : ["--print", request.prompt, "--output-format", "stream-json"];

  return { command, args };
}

export function runProvider(request: ProviderRequest): Promise<HeadlessResult> {
  const { command, args } = buildProviderInvocation(request);
  return runHeadless({
    command,
    args,
    cwd: path.resolve(request.cwd),
    timeoutMs: request.timeoutMs,
    maxOutputBytes: request.maxOutputBytes,
    onEvent: request.onEvent,
  });
}
