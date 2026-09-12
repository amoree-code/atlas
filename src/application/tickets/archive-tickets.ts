import { access, mkdir, readdir, readFile, rename, rmdir } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export type ArchiveResult = {
  candidates: string[];
  skipped: Array<{ id: string; reason: string }>;
  moved: string[];
};

const field = (source: string, name: string): string =>
  source.match(new RegExp(`^${name}:\\s*(.+)$`, "m"))?.[1]?.trim().replace(/^['"]|['"]$/g, "") ?? "";

const projectArchiveName = (project: string): string => project.toLowerCase() === "atlas" ? "Atlas" : project;

export async function archiveDoneTickets(root = atlasPath("projects", "atlas", "tickets"), apply = false): Promise<ArchiveResult> {
  const result: ArchiveResult = { candidates: [], skipped: [], moved: [] };
  let entries;
  try { entries = await readdir(root, { withFileTypes: true }); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return result; throw error; }

  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    const sourceDirectory = path.join(root, entry.name);
    const taskFile = path.join(sourceDirectory, "task.md");
    try { await access(taskFile); } catch { continue; }
    const source = await readFile(taskFile, "utf8");
    const id = field(source, "id") || entry.name;
    const state = field(source, "state");
    if (state !== "done") continue;
    if (source.match(/- "\[ \] /)) {
      result.skipped.push({ id, reason: "unchecked work" });
      continue;
    }
    result.candidates.push(id);
    if (!apply) continue;

    const project = field(source, "project") || "atlas";
    const destinationDirectory = path.join(root, "archive", projectArchiveName(project), id);
    const destination = path.join(destinationDirectory, "task.md");
    try { await access(destination); result.skipped.push({ id, reason: "archive destination exists" }); continue; }
    catch (error) { if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error; }
    await mkdir(destinationDirectory, { recursive: true });
    await rename(taskFile, destination);
    try { await rmdir(sourceDirectory); } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "ENOTEMPTY") throw error;
    }
    result.moved.push(id);
  }
  return result;
}
