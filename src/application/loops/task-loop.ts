import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { runAgent, type ProviderExecutor } from "../runs/run-agent.js";
import { atlasPath, resolveWithin } from "../../paths.js";

export type TaskLoopStatus = "active" | "paused" | "completed" | "failed" | "stopped";
export type TaskLoop = {
  id: string;
  taskId: string;
  profile: string;
  prompt: string;
  cwd: string;
  status: TaskLoopStatus;
  approved: boolean;
  maxIterations: number;
  intervalMs: number;
  maxAttempts: number;
  iterations: number;
  failures: number;
  nextRunAt: string;
  lastSessionId: string | null;
  lastError: string | null;
  checkpoint: string;
};

const loopsFile = () => atlasPath("system", "loops.json");

export async function listTaskLoops(): Promise<TaskLoop[]> {
  try { return JSON.parse(await readFile(loopsFile(), "utf8")) as TaskLoop[]; }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export async function startTaskLoop(input: {
  taskId: string; profile: string; prompt: string; cwd: string;
  approved: boolean; maxIterations?: number; intervalMs?: number; maxAttempts?: number;
}): Promise<TaskLoop> {
  if (!input.approved) throw new Error("Loop start requires explicit approval.");
  if (!input.taskId || !/^T-\d+$/.test(input.taskId)) throw new Error("Loop requires a valid task id.");
  const loop: TaskLoop = {
    id: `loop-${randomUUID()}`,
    taskId: input.taskId,
    profile: input.profile,
    prompt: input.prompt.trim(),
    cwd: input.cwd,
    status: "active",
    approved: true,
    maxIterations: bounded(input.maxIterations ?? 10, 1, 100),
    intervalMs: bounded(input.intervalMs ?? 60_000, 1_000, 86_400_000),
    maxAttempts: bounded(input.maxAttempts ?? 2, 1, 5),
    iterations: 0,
    failures: 0,
    nextRunAt: new Date().toISOString(),
    lastSessionId: null,
    lastError: null,
    checkpoint: "Loop created; inspect the task and choose the first bounded action.",
  };
  await saveLoops([...(await listTaskLoops()), loop]);
  return loop;
}

export async function stopTaskLoop(id: string): Promise<TaskLoop> {
  const loops = await listTaskLoops();
  const loop = loops.find((item) => item.id === id);
  if (!loop) throw new Error(`Loop not found: ${id}`);
  loop.status = "stopped";
  await saveLoops(loops);
  return loop;
}

export async function runTaskLoopsOnce(cwd: string, execute?: ProviderExecutor): Promise<string[]> {
  const loops = await listTaskLoops();
  const ran: string[] = [];
  for (const loop of loops) {
    if (loop.status !== "active" || Date.parse(loop.nextRunAt) > Date.now()) continue;
    if (loop.iterations >= loop.maxIterations) { loop.status = "failed"; loop.lastError = "iteration budget exhausted"; continue; }
    const sessionId = randomUUID();
    loop.iterations += 1;
    loop.lastSessionId = sessionId;
    try {
      const session = await runAgent({
        sessionId,
        profileName: loop.profile,
        prompt: `${loop.prompt}\n\nLoop checkpoint: ${loop.checkpoint}\nWork only on task ${loop.taskId}. Complete one bounded action, verify it, and record the next checkpoint.`,
        cwd: loop.cwd || cwd,
        taskId: loop.taskId,
        runContract: {
          runId: loop.id,
          sessionId,
          profile: loop.profile,
          workingDirectory: loop.cwd || cwd,
          allowedTools: [],
          deniedTools: [],
          stopConditions: ["task complete", "missing input", "approval required", "verification failure", "budget exhausted"],
          approval: { required: true, approved: loop.approved },
          budget: { timeoutMs: loop.intervalMs, maxAttempts: loop.maxAttempts, maxOutputBytes: 1_000_000 },
        },
      }, execute);
      if (session.status !== "completed") throw new Error(`session ${session.status}`);
      loop.checkpoint = `Iteration ${loop.iterations} completed; inspect task ${loop.taskId} before continuing.`;
      loop.lastError = null;
      loop.nextRunAt = new Date(Date.now() + loop.intervalMs).toISOString();
      if (await taskIsDone(loop.taskId)) loop.status = "completed";
      ran.push(loop.id);
    } catch (error) {
      loop.failures += 1;
      loop.lastError = error instanceof Error ? error.message : String(error);
      loop.nextRunAt = new Date(Date.now() + loop.intervalMs).toISOString();
      if (loop.failures >= loop.maxAttempts) loop.status = "failed";
    }
  }
  await saveLoops(loops);
  return ran;
}

export async function runTaskLoopWorker(
  cwd: string,
  options: { signal?: AbortSignal; pollMs?: number } = {},
): Promise<void> {
  const pollMs = options.pollMs ?? 30_000;
  while (!options.signal?.aborted) {
    await runTaskLoopsOnce(cwd);
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, pollMs);
      options.signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
    });
  }
}

async function taskIsDone(id: string): Promise<boolean> {
  const file = resolveWithin(atlasPath("projects", "atlas", "tasks"), id, "task.md");
  const source = await readFile(file, "utf8");
  return /^state:\s*done\s*$/m.test(source);
}

async function saveLoops(loops: TaskLoop[]): Promise<void> {
  const target = loopsFile();
  await mkdir(path.dirname(target), { recursive: true });
  const temp = `${target}.${process.pid}.tmp`;
  await writeFile(temp, `${JSON.stringify(loops, null, 2)}\n`, { mode: 0o600 });
  await rename(temp, target);
}

function bounded(value: number, min: number, max: number): number {
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`Value must be an integer between ${min} and ${max}.`);
  return value;
}
