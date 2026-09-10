import { readFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import type { Profile } from "../../domain/profiles/profile.js";
import { validateProfile } from "../../domain/profiles/profile-validator.js";

export async function loadProfile(name: string): Promise<Profile> {
  const file = path.join(atlasPath("profiles"), `${name}.json`);
  return validateProfile(JSON.parse(await readFile(file, "utf8")));
}
