import { appendFile, mkdir } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { atlasPath } from "../../paths.js";

const MAX_PAYLOAD = 64_000;
const secretPatterns = [
  /(?:sk-(?:ant-)?|AIza|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{8,}/gi,
  /\bBearer\s+[A-Za-z0-9._~+/=-]{20,}/gi,
  /(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|authorization)\s*[:=]\s*["']?[A-Za-z0-9._~+/=-]{12,}["']?/gi,
  /\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b/g,
  /-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |OPENSSH |EC )?PRIVATE KEY-----/g,
];
const homePath = os.homedir().replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const privatePathPattern = new RegExp(`${homePath}(?:[/\\\\][^\\s/'"]+)*`, "g");

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
  let safe = value;
  for (const pattern of secretPatterns)
    safe = safe.replace(pattern, "[REDACTED]");
  return safe
    .replace(privatePathPattern, "[PRIVATE_PATH]")
    .slice(0, MAX_PAYLOAD);
}

export async function appendRuntimeLog(log: RuntimeLog): Promise<void> {
  const safe = {
    ...log,
    payload:
      log.payload === undefined ? undefined : redactRuntimeText(log.payload),
  };
  await mkdir(atlasPath("system", "runtime", "logs"), { recursive: true });
  await appendFile(
    path.join(atlasPath("system", "runtime", "logs"), "runtime.jsonl"),
    `${JSON.stringify(safe)}\n`,
    "utf8",
  );
}
