import { readFile } from "node:fs/promises";
import path from "node:path";
import {
  type Skill,
  type SkillMetadata,
  skillMetadataSchema,
} from "../../domain/skills/skill.js";
import { validateSkill } from "../../domain/skills/skill-validator.js";
import { atlasPath, atlasRoot, enginePath } from "../../paths.js";

const catalogPath = enginePath("skills", "index.json");

export async function listSkills(): Promise<SkillMetadata[]> {
  return readCatalog(catalogPath);
}

export async function loadSkill(name: string): Promise<Skill> {
  return loadSkillFromRoots(name, [enginePath("skills")]);
}

export async function loadSkills(
  names: string[],
  maxBytes = 32_000,
  cwd = atlasRoot(),
): Promise<Skill[]> {
  const loaded: Skill[] = [];
  const seen = new Set<string>();
  let bytes = 0;
  const roots = [
    enginePath("skills"),
    atlasPath("system", "integrations", "claude-code", "skills"),
    projectSkillRoot(cwd),
  ].filter(Boolean) as string[];
  for (const name of names) {
    if (seen.has(name) || bytes >= maxBytes) continue;
    const skill = await loadSkillFromRoots(name, roots);
    const instructions = skill.instructions.slice(0, maxBytes - bytes);
    if (!instructions) break;
    loaded.push({ ...skill, instructions });
    seen.add(name);
    bytes += Buffer.byteLength(instructions);
  }
  return loaded;
}

async function loadSkillFromRoots(
  name: string,
  roots: string[],
): Promise<Skill> {
  for (const root of roots) {
    const catalog = path.join(root, "index.json");
    try {
      const metadata = (await readCatalog(catalog)).find(
        (skill) => skill.name === name,
      );
      if (!metadata) continue;
      const instructions = await readFile(
        path.join(root, metadata.category, name, "SKILL.md"),
        "utf8",
      );
      return validateSkill({ ...metadata, instructions });
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") continue;
      throw error;
    }
  }
  throw new Error(`Skill not found: ${name}`);
}

async function readCatalog(file: string): Promise<SkillMetadata[]> {
  try {
    return skillMetadataSchema
      .array()
      .parse(JSON.parse(await readFile(file, "utf8")));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

function projectSkillRoot(cwd: string): string | null {
  const projectsRoot = path.resolve(atlasPath("projects"));
  const relative = path.relative(projectsRoot, path.resolve(cwd));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative))
    return null;
  const parts = relative.split(path.sep);
  const grouped = [
    "work",
    "freelance",
    "personal",
    "vendor",
    "archive",
  ].includes(parts[0] ?? "");
  const projectParts = grouped ? parts.slice(0, 2) : parts.slice(0, 1);
  return path.join(projectsRoot, ...projectParts, "skills");
}
