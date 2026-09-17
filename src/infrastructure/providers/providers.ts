import path from "node:path";
import { runHeadless, type HeadlessResult, type RuntimeEvent } from "../process/cli-process.js";
import { resolveOriginalExecutable } from "./provider-registry.js";

export type HeadlessProvider = "claude" | "codex" | "gemini" | "antigravity" | "hermes" | "kilo" | "kimi";
export type ProviderAdapter = { provider: HeadlessProvider; capabilities: readonly string[]; readOnlyArgs?: readonly string[]; build: (request: ProviderRequest) => string[] };

export type ProviderRequest = {
  provider: HeadlessProvider;
  prompt: string;
  cwd: string;
  clientHome?: string;
  resumeId?: string;
  timeoutMs?: number;
  maxOutputBytes?: number;
  onEvent?: (event: RuntimeEvent) => void;
  readOnly?: boolean;
};

export const providerAdapterRegistry: Readonly<Record<HeadlessProvider, ProviderAdapter>> = {
  claude: { provider: "claude", capabilities: ["headless", "resume", "read-only"], readOnlyArgs: ["--permission-mode", "plan", "--restricted"], build: (request) => [...(request.resumeId ? ["--resume", request.resumeId] : []), ...(request.readOnly ? ["--permission-mode", "plan", "--restricted"] : []), "-p", request.prompt, "--verbose", "--output-format", "stream-json"] },
  codex: { provider: "codex", capabilities: ["headless", "read-only"], readOnlyArgs: ["--sandbox", "read-only"], build: (request) => ["exec", ...(request.readOnly ? ["--sandbox", "read-only"] : []), "--json", "--skip-git-repo-check", request.prompt] },
  gemini: { provider: "gemini", capabilities: ["headless", "read-only"], readOnlyArgs: ["--approval-mode=plan"], build: (request) => [...(request.readOnly ? ["--approval-mode=plan"] : []), "--prompt", request.prompt, "--output-format", "stream-json"] },
  antigravity: { provider: "antigravity", capabilities: ["headless", "read-only"], readOnlyArgs: ["--mode", "plan", "--sandbox"], build: (request) => [...(request.readOnly ? ["--mode", "plan", "--sandbox"] : []), "--print", request.prompt, "--output-format", "stream-json"] },
  hermes: { provider: "hermes", capabilities: ["headless"], build: (request) => ["-z", request.prompt] },
  kilo: { provider: "kilo", capabilities: ["headless"], build: (request) => ["run", "--auto", request.prompt] },
  kimi: { provider: "kimi", capabilities: ["headless", "read-only"], readOnlyArgs: ["--plan"], build: (request) => [...(request.readOnly ? ["--plan"] : []), "--prompt", request.prompt, "--print", "--output-format", "stream-json"] },
};

export function buildProviderInvocation(request: ProviderRequest): { command: string; args: string[] } {
  const command = request.provider === "antigravity" ? "agy" : request.provider;
  const adapter = providerAdapterRegistry[request.provider];
  if (request.readOnly) assertProviderSupportsReadOnly(request.provider);
  const args = adapter.build(request);

  return { command, args };
}

export function assertProviderSupportsReadOnly(provider: HeadlessProvider): void {
  if (!providerAdapterRegistry[provider].capabilities.includes("read-only")) throw new Error(`Provider cannot enforce read-only execution: ${provider}`);
}

export function runProvider(request: ProviderRequest): Promise<HeadlessResult> {
  const { command, args } = buildProviderInvocation(request);
  return runHeadless({
    command: resolveOriginalExecutable(command),
    args,
    cwd: path.resolve(request.cwd),
    env: request.provider === "hermes" && request.clientHome ? { HERMES_HOME: request.clientHome } : undefined,
    timeoutMs: request.timeoutMs,
    maxOutputBytes: request.maxOutputBytes,
    onEvent: request.onEvent,
  });
}
