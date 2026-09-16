import { readFile, stat } from "node:fs/promises";
import path from "node:path";
import { atlasPath, resolveWithin } from "../../paths.js";
import type { Profile } from "../../domain/profiles/profile.js";
import { validateProfile } from "../../domain/profiles/profile-validator.js";

export async function loadProfile(name: string): Promise<Profile> {
  if (!/^[A-Za-z0-9_-]+$/.test(name)) throw new Error("Invalid profile name");
  const root = atlasPath("system", "profiles");
  const file = resolveWithin(root, `${name}.json`);
  try {
    return validateProfile(JSON.parse(await readFile(file, "utf8")));
  } catch {
    // Fall through to the legacy directory form during migration.
  }
  const directory = resolveWithin(root, name);
  if ((await stat(directory)).isDirectory()) {
    const input = JSON.parse(await readFile(path.join(directory, "profile.json"), "utf8")) as Record<string, unknown>;
    const instructions = await readFile(path.join(directory, "instructions.md"), "utf8").catch(() => "");
    return validateProfile({ ...input, instructions });
  }
  throw new Error(`Profile not found: ${name}`);
}
