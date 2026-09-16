import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, readdir, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export type ConflictSide = "vault" | "atlas";
export type ObsidianConflict = {
  version: 1;
  id: string;
  path: string;
  baselineSha256: string | null;
  vaultSha256: string | null;
  atlasSha256: string | null;
  vaultContent?: string;
  atlasContent?: string;
  proposedContent?: string;
  createdAt: string;
  source?: string;
};

export function conflictsDirectory(root = atlasPath("system", "integrations", "obsidian", "conflicts")): string {
  return root;
}

function digest(content: string | undefined | null): string | null {
  return content === undefined || content === null ? null : createHash("sha256").update(content).digest("hex");
}

export async function appendConflict(input: Omit<ObsidianConflict, "version" | "id" | "createdAt">, directory = conflictsDirectory()): Promise<string> {
  await mkdir(directory, { recursive: true });
  const id = `${new Date().toISOString().replaceAll(/[:.]/g, "-")}-${randomUUID()}`;
  const record: ObsidianConflict = {
    version: 1,
    id,
    ...input,
    createdAt: new Date().toISOString(),
  };
  const file = path.join(directory, `${id}.json`);
  await writeFile(file, `${JSON.stringify(record, null, 2)}\n`, { encoding: "utf8", mode: 0o600 });
  return file;
}

export async function listConflictLogs(directory = conflictsDirectory()): Promise<ObsidianConflict[]> {
  try {
    const entries = await readdir(directory, { withFileTypes: true });
    const records: ObsidianConflict[] = [];
    for (const entry of entries.filter((item) => item.isFile() && item.name.endsWith(".json"))) {
      records.push(JSON.parse(await readFile(path.join(directory, entry.name), "utf8")) as ObsidianConflict);
    }
    return records;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

function changedFromBaseline(record: ObsidianConflict, side: ConflictSide): boolean {
  const hash = side === "vault" ? record.vaultSha256 : record.atlasSha256;
  return hash !== record.baselineSha256;
}

export async function resolveConflict(id: string, keep: ConflictSide, options: {
  directory?: string;
  apply?: (record: ObsidianConflict, keep: ConflictSide) => Promise<void>;
} = {}): Promise<{ id: string; keep: ConflictSide; status: "auto-resolved" | "manual-required"; archived: string }> {
  if (!id || path.basename(id) !== id) throw new Error("Conflict id must be a conflict filename");
  const directory = options.directory ?? conflictsDirectory();
  const filename = id.endsWith(".json") ? id : `${id}.json`;
  const source = path.join(directory, filename);
  const record = JSON.parse(await readFile(source, "utf8")) as ObsidianConflict;
  const vaultChanged = changedFromBaseline(record, "vault");
  const atlasChanged = changedFromBaseline(record, "atlas");
  const status = vaultChanged !== atlasChanged ? "auto-resolved" : "manual-required";
  if (status === "auto-resolved" && options.apply) await options.apply(record, keep);
  const archiveDirectory = path.join(directory, "resolved");
  await mkdir(archiveDirectory, { recursive: true });
  const archived = path.join(archiveDirectory, id);
  await rename(source, archived);
  return { id: filename, keep, status, archived };
}

export function contentHash(content: string | null | undefined): string | null {
  return digest(content);
}
