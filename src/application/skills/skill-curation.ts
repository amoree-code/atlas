import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export type SkillCandidate = { id: string; name: string; version: string; instructions: string; status: "candidate" | "rejected" | "promoted"; createdAt: string };
const file = () => atlasPath("system", "skills", "candidates.json");
async function load(): Promise<SkillCandidate[]> { try { return JSON.parse(await readFile(file(), "utf8")); } catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return []; throw error; } }
async function save(items: SkillCandidate[]): Promise<void> { await mkdir(path.dirname(file()), { recursive: true }); await writeFile(file(), `${JSON.stringify(items, null, 2)}\n`, { mode: 0o600 }); }

export async function addSkillCandidate(candidate: Omit<SkillCandidate, "version" | "status" | "createdAt">): Promise<SkillCandidate> {
  if (!candidate.id || !candidate.name || !candidate.instructions || candidate.instructions.length > 32_000 || /(api[_ -]?key|token|password|secret)\s*[:=]/i.test(candidate.instructions)) throw new Error("Invalid or sensitive skill candidate");
  const items = await load();
  if (items.some((item) => item.id === candidate.id || item.name === candidate.name)) throw new Error("Duplicate skill candidate");
  const result = { ...candidate, version: "1.0.0", status: "candidate" as const, createdAt: new Date().toISOString() };
  await save([...items, result]); return result;
}

export async function listSkillCandidates(): Promise<SkillCandidate[]> { return load(); }
export async function reviewSkillCandidate(id: string, status: "rejected" | "promoted"): Promise<SkillCandidate> {
  const items = await load(); const item = items.find((candidate) => candidate.id === id);
  if (!item) throw new Error(`Skill candidate not found: ${id}`);
  item.status = status; await save(items); return item;
}
