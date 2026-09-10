import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

const MAX_PAYLOAD = 64_000;
const secretPattern = /(?:sk-(?:ant-)?|AIza|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}/g;

export type RuntimeLog = {
  timestamp: string;
  event: string;
  correlationId: string;
  provider?: string;
  sessionId?: string;
  status?: string;
  payload?: string;
};

export function redactRuntimeText(value: string): string {
  return value.replace(secretPattern, "[REDACTED]").replace(/\/Users\/[^\s/'"`]+/g, "[PRIVATE_PATH]").slice(0, MAX_PAYLOAD);
}

export async function appendRuntimeLog(log: RuntimeLog): Promise<void> {
  const safe = { ...log, payload: log.payload === undefined ? undefined : redactRuntimeText(log.payload) };
  await mkdir(atlasPath("logs"), { recursive: true });
  await appendFile(path.join(atlasPath("logs"), "runtime.jsonl"), `${JSON.stringify(safe)}\n`, "utf8");
}
