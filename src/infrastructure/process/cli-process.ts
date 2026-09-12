import { spawn } from "node:child_process";

export type RuntimeEvent = {
  type: "json" | "text";
  data: unknown;
};

export type HeadlessRequest = {
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
  timeoutMs?: number;
  maxOutputBytes?: number;
  onEvent?: (event: RuntimeEvent) => void;
};

export type HeadlessResult = {
  exitCode: number;
  events: RuntimeEvent[];
  stderr: string;
};

export function runHeadless(request: HeadlessRequest): Promise<HeadlessResult> {
  return new Promise((resolve, reject) => {
    const child = spawn(request.command, request.args, {
      cwd: request.cwd,
      env: { ...process.env, ...request.env },
      stdio: ["ignore", "pipe", "pipe"],
    });
    const events: RuntimeEvent[] = [];
    let stdoutBuffer = "";
    let stderr = "";
    let timedOut = false;
    let outputLimitExceeded = false;
    let outputBytes = 0;
    let forceKillTimer: NodeJS.Timeout | undefined;
    const terminate = (): void => {
      child.kill("SIGTERM");
      forceKillTimer = setTimeout(() => child.kill("SIGKILL"), 100);
    };
    const timer = setTimeout(() => {
      timedOut = true;
      terminate();
    }, request.timeoutMs ?? 60_000);

    const emitLines = (chunk: Buffer): void => {
      const maxOutputBytes = request.maxOutputBytes ?? Number.MAX_SAFE_INTEGER;
      if (outputBytes + chunk.byteLength > maxOutputBytes) {
        outputLimitExceeded = true;
        terminate();
        return;
      }
      outputBytes += chunk.byteLength;
      stdoutBuffer += chunk.toString("utf8");
      const lines = stdoutBuffer.split(/\r?\n/);
      stdoutBuffer = lines.pop() ?? "";
      for (const line of lines) {
        if (!line) continue;
        let event: RuntimeEvent;
        try {
          event = { type: "json", data: JSON.parse(line) };
        } catch {
          event = { type: "text", data: line };
        }
        events.push(event);
        request.onEvent?.(event);
      }
    };

    child.stdout.on("data", emitLines);
    child.stderr.on("data", (chunk: Buffer) => { stderr += chunk.toString("utf8"); });
    child.once("error", (error) => {
      clearTimeout(timer);
      if (forceKillTimer) clearTimeout(forceKillTimer);
      if (!timedOut) reject(error);
    });
    child.once("close", (exitCode) => {
      clearTimeout(timer);
      if (forceKillTimer) clearTimeout(forceKillTimer);
      if (stdoutBuffer) emitLines(Buffer.from("\n"));
      resolve({ exitCode: timedOut ? 124 : outputLimitExceeded ? 125 : (exitCode ?? 1), events, stderr: timedOut ? `${stderr}Process timed out.\n` : outputLimitExceeded ? `${stderr}Output budget exceeded.\n` : stderr });
    });
  });
}
