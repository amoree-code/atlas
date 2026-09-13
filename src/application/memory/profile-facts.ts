import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

const maxFacts = 100;
const maxFactBytes = 2_000;

export type ProfileFact = { key: string; value: string; updatedAt: string };

function fileFor(profile: string): string {
  return atlasPath("system", "memory", "profiles", `${profile}.json`);
}

export async function readProfileFacts(profile: string): Promise<ProfileFact[]> {
  try {
    const facts = JSON.parse(await readFile(fileFor(profile), "utf8")) as ProfileFact[];
    return Array.isArray(facts) ? facts.slice(0, maxFacts) : [];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

export async function writeProfileFact(profile: string, key: string, value: string): Promise<ProfileFact> {
  if (!/^[a-zA-Z0-9._-]+$/.test(key)) throw new Error("Fact key must contain only letters, numbers, dot, underscore, or hyphen");
  if (!value.trim() || Buffer.byteLength(value) > maxFactBytes) throw new Error("Fact value is empty or exceeds 2000 bytes");
  const fact = { key, value: value.trim(), updatedAt: new Date().toISOString() };
  const facts = (await readProfileFacts(profile)).filter((item) => item.key !== key);
  facts.unshift(fact);
  await mkdir(path.dirname(fileFor(profile)), { recursive: true });
  await writeFile(fileFor(profile), `${JSON.stringify(facts.slice(0, maxFacts), null, 2)}\n`, { mode: 0o600 });
  return fact;
}

export async function deleteProfileFact(profile: string, key: string): Promise<boolean> {
  const facts = await readProfileFacts(profile);
  const remaining = facts.filter((fact) => fact.key !== key);
  if (remaining.length === facts.length) return false;
  await mkdir(path.dirname(fileFor(profile)), { recursive: true });
  await writeFile(fileFor(profile), `${JSON.stringify(remaining, null, 2)}\n`, { mode: 0o600 });
  return true;
}

export function formatProfileFacts(facts: ProfileFact[]): string {
  return facts.length ? `## Durable profile facts\n${facts.map((fact) => `- ${fact.key}: ${fact.value}`).join("\n")}` : "";
}
