import { mkdir, open, readFile, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import { runAgent, type ProviderExecutor } from "../runs/run-agent.js";

export type Schedule = { id: string; profile: string; prompt: string; intervalMs: number; nextRunAt: string; enabled: boolean; attempts?: number; retryAt?: string };
const file = () => atlasPath("system", "schedules.json");
const running = new Set<string>();

export async function listSchedules(): Promise<Schedule[]> {
  try { return JSON.parse(await readFile(file(), "utf8")) as Schedule[]; }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; }
}

export async function saveSchedule(schedule: Schedule): Promise<void> {
  if (!Number.isFinite(schedule.intervalMs) || schedule.intervalMs < 1_000) throw new Error("Schedule interval must be at least 1000ms");
  const schedules = (await listSchedules()).filter((item) => item.id !== schedule.id);
  schedules.push(schedule);
  await mkdir(path.dirname(file()), { recursive: true });
  await writeFile(file(), `${JSON.stringify(schedules, null, 2)}\n`, { mode: 0o600 });
}

export async function setScheduleEnabled(id: string, enabled: boolean): Promise<Schedule> {
  const schedules = await listSchedules(); const schedule = schedules.find((item) => item.id === id);
  if (!schedule) throw new Error(`Schedule not found: ${id}`);
  schedule.enabled = enabled; await writeFile(file(), `${JSON.stringify(schedules, null, 2)}\n`, { mode: 0o600 }); return schedule;
}

export async function runSchedule(id: string, cwd: string, execute?: ProviderExecutor): Promise<void> {
  const schedule = (await listSchedules()).find((item) => item.id === id);
  if (!schedule) throw new Error(`Schedule not found: ${id}`);
  await runAgent({ profileName: schedule.profile, prompt: schedule.prompt, cwd }, execute);
}

export async function runDueSchedules(cwd: string, execute?: ProviderExecutor): Promise<string[]> {
  const now = Date.now();
  const schedules = await listSchedules();
  const ran: string[] = [];
  for (const schedule of schedules) {
    if (!schedule.enabled || Date.parse(schedule.nextRunAt) > now || (schedule.retryAt && Date.parse(schedule.retryAt) > now) || running.has(schedule.id)) continue;
    const lease = await acquireLease(schedule.id);
    if (!lease) continue;
    running.add(schedule.id);
    try {
      await runAgent({ profileName: schedule.profile, prompt: schedule.prompt, cwd }, execute);
      schedule.nextRunAt = new Date(now + schedule.intervalMs).toISOString();
      ran.push(schedule.id);
    } finally {
      running.delete(schedule.id);
      await lease.close();
      await unlink(leaseFile(schedule.id)).catch(() => undefined);
    }
  }
  if (ran.length) await writeFile(file(), `${JSON.stringify(schedules, null, 2)}\n`, { mode: 0o600 });
  return ran;
}

export async function runSchedulerWorkerOnce(cwd: string, execute?: ProviderExecutor): Promise<string[]> {
  const schedules = await listSchedules(); const ran: string[] = [];
  for (const schedule of schedules) {
    if (!schedule.enabled || Date.parse(schedule.nextRunAt) > Date.now()) continue;
    const lease = leaseFile(schedule.id);
    await mkdir(path.dirname(lease), { recursive: true });
    let handle;
    try { handle = await open(lease, "wx"); await handle.writeFile(`${process.pid}\n`); }
    catch (error) { if ((error as NodeJS.ErrnoException).code === "EEXIST") continue; throw error; }
    try {
      try {
        await runAgent({ profileName: schedule.profile, prompt: schedule.prompt, cwd }, execute);
        schedule.nextRunAt = new Date(Date.now() + schedule.intervalMs).toISOString(); schedule.attempts = 0; delete schedule.retryAt; ran.push(schedule.id);
      } catch {
        schedule.attempts = (schedule.attempts ?? 0) + 1;
        const delay = Math.min(schedule.intervalMs * 2 ** Math.min(schedule.attempts, 5), 3_600_000);
        schedule.retryAt = new Date(Date.now() + delay).toISOString(); schedule.nextRunAt = schedule.retryAt;
      }
    } finally { await handle.close(); await unlink(lease).catch(() => undefined); }
  }
  await writeFile(file(), `${JSON.stringify(schedules, null, 2)}\n`, { mode: 0o600 });
  return ran;
}

export async function runSchedulerWorker(cwd: string, options: { pollMs?: number; signal?: AbortSignal; execute?: ProviderExecutor } = {}): Promise<void> {
  const pollMs = Math.max(1_000, options.pollMs ?? 30_000);
  while (!options.signal?.aborted) {
    await runSchedulerWorkerOnce(cwd, options.execute);
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, pollMs);
      options.signal?.addEventListener("abort", () => { clearTimeout(timer); resolve(); }, { once: true });
    });
  }
}

function leaseFile(id: string): string { return atlasPath("system", "schedules", `${id}.lease`); }

async function acquireLease(id: string): Promise<Awaited<ReturnType<typeof open>> | null> {
  const lease = leaseFile(id);
  await mkdir(path.dirname(lease), { recursive: true });
  try {
    const handle = await open(lease, "wx");
    await handle.writeFile(`${process.pid}\n`);
    return handle;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "EEXIST") return null;
    throw error;
  }
}
