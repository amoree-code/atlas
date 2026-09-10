import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { providerCapabilitySchema, type ProviderCapability } from "../../domain/providers/provider-capability.js";
import type { HeadlessProvider } from "./providers.js";

const execFileAsync = promisify(execFile);
const commands: Record<HeadlessProvider, string> = { claude: "claude", codex: "codex", gemini: "gemini", antigravity: "agy" };

export async function discoverProviderCapabilities(provider: HeadlessProvider): Promise<ProviderCapability> {
  const command = commands[provider];
  let installed = false;
  try { await execFileAsync("which", [command]); installed = true; } catch { /* represented as unavailable */ }
  return providerCapabilitySchema.parse({
    provider, command, installed, headless: true, resume: provider === "claude",
    streaming: true, structuredOutput: true, authentication: "cli-managed",
  });
}

export function assertProviderCapability(capability: ProviderCapability, requirement: "headless" | "resume" | "streaming" | "structuredOutput"): void {
  if (!capability.installed) throw new Error(`Provider CLI not installed: ${capability.command}`);
  if (!capability[requirement]) throw new Error(`Provider ${capability.provider} does not support ${requirement}`);
}
