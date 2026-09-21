import type { Dirent } from "node:fs";
import {
  access,
  mkdir,
  readdir,
  readFile,
  rename,
  rmdir,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { atlasPath, resolveWithin } from "../../paths.js";

export type ArchiveResult = {
  candidates: string[];
  skipped: Array<{ id: string; reason: string }>;
  moved: string[];
  repaired: string[];
};

export type CompletionResult = ArchiveResult & { id: string; state: "done" };

const field = (source: string, name: string): string =>
  source
    .match(new RegExp(`^${name}:\\s*(.+)$`, "m"))?.[1]
    ?.trim()
    .replace(/^['"]|['"]$/g, "") ?? "";

const projectArchiveName = (project: string): string =>
  project.toLowerCase() === "atlas" ? "Atlas" : project;

function setState(source: string, state: string): string {
  return source.replace(/^state:\s*.+$/m, `state: ${state}`);
}

export async function completeTask(
  id: string,
  root = atlasPath("projects", "atlas", "tasks"),
): Promise<CompletionResult> {
  const taskFile = resolveWithin(root, id, "task.md");
  const source = await readFile(taskFile, "utf8");
  const checklist = source.match(/- "\[[ x]\] .*"/g);
  if (checklist) {
    if (checklist.some((line) => line.includes("[ ]")))
      throw new Error(`Cannot complete ${id}: unchecked work`);
  } else {
    const verification = source
      .match(/\n## Verification\n\n([\s\S]*?)(?=\n## |$)/)?.[1]
      ?.trim();
    if (!verification || /^pending\b/i.test(verification))
      throw new Error(`Cannot complete ${id}: verification is pending`);
  }
  if (field(source, "state") !== "done")
    await writeFile(taskFile, setState(source, "done"));
  const archived = await archiveDoneTasks(root, true);
  return { id, state: "done", ...archived };
}

export async function archiveDoneTasks(
  root = atlasPath("projects", "atlas", "tasks"),
  apply = false,
): Promise<ArchiveResult> {
  const result: ArchiveResult = {
    candidates: [],
    skipped: [],
    moved: [],
    repaired: [],
  };
  const archiveRoot = resolveWithin(root, "archive");
  let entries: Dirent[];
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return result;
    throw error;
  }

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    const sourceDirectory = resolveWithin(root, entry.name);
    const taskFile = resolveWithin(root, entry.name, "task.md");
    try {
      await access(taskFile);
    } catch {
      const archivedDirectory = resolveWithin(archiveRoot, "Atlas", entry.name);
      try {
        await access(path.join(archivedDirectory, "task.md"));
      } catch {
        continue;
      }
      if (!apply) continue;
      for (const artifact of await readdir(sourceDirectory, {
        withFileTypes: true,
      })) {
        const destination = resolveWithin(archivedDirectory, artifact.name);
        try {
          await access(destination);
          result.skipped.push({
            id: entry.name,
            reason: `archive artifact exists: ${artifact.name}`,
          });
          continue;
        } catch (error) {
          if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
        }
        await rename(path.join(sourceDirectory, artifact.name), destination);
      }
      try {
        await rmdir(sourceDirectory);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOTEMPTY") throw error;
      }
      result.repaired.push(entry.name);
      continue;
    }
    const source = await readFile(taskFile, "utf8");
    const id = field(source, "id") || entry.name;
    const state = field(source, "state");
    if (state !== "done" && state !== "cancelled") continue;
    if (source.match(/- "\[ \] /)) {
      result.skipped.push({ id, reason: "unchecked work" });
      continue;
    }
    result.candidates.push(id);
    if (!apply) continue;

    const project = field(source, "project") || "atlas";
    const destinationDirectory = resolveWithin(
      archiveRoot,
      projectArchiveName(project),
      id,
    );
    try {
      await access(destinationDirectory);
      result.skipped.push({ id, reason: "archive destination exists" });
      continue;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
    }
    await mkdir(path.dirname(destinationDirectory), { recursive: true });
    await rename(sourceDirectory, destinationDirectory);
    result.moved.push(id);
  }
  return result;
}
