import { createHash } from "node:crypto";
import { access, readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

const MAX_FILES = 10_000;
const MAX_BYTES = 50 * 1024 * 1024;

export type ObsidianConnection = {
  enabled: boolean;
  mode: "read-only";
  vaultPath: string;
};

export type ObsidianNote = {
  path: string;
  bytes: number;
  sha256: string;
  properties: Record<string, string>;
  issues: string[];
};

export type ObsidianDiscovery = {
  vaultPath: string;
  noteCount: number;
  totalBytes: number;
  notes: ObsidianNote[];
  issues: string[];
};

const connectionPath = (): string => atlasPath("system", "integrations", "obsidian", "connection.json");

export async function loadObsidianConnection(file = connectionPath()): Promise<ObsidianConnection> {
  const source = JSON.parse(await readFile(file, "utf8")) as Partial<ObsidianConnection>;
  if (source.enabled !== true) throw new Error("Obsidian integration is disabled");
  if (source.mode !== "read-only") throw new Error("Obsidian discovery requires mode: read-only");
  if (!source.vaultPath || !path.isAbsolute(source.vaultPath)) throw new Error("Obsidian vaultPath must be absolute");
  const vault = await stat(source.vaultPath);
  if (!vault.isDirectory()) throw new Error("Obsidian vaultPath must be a directory");
  return { enabled: true, mode: "read-only", vaultPath: source.vaultPath };
}

function properties(content: string): Record<string, string> {
  if (!content.startsWith("---\n")) return {};
  const end = content.indexOf("\n---", 4);
  if (end < 0) return {};
  return Object.fromEntries(content.slice(4, end).split("\n")
    .map((line) => line.match(/^([A-Za-z][\w-]*):\s*(.*)$/))
    .filter((match): match is RegExpMatchArray => Boolean(match))
    .map((match) => [match[1], match[2].trim()]));
}

async function collect(directory: string, root: string, notes: ObsidianNote[], total: { files: number; bytes: number }): Promise<void> {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      await collect(file, root, notes, total);
      continue;
    }
    if (!entry.name.endsWith(".md")) continue;
    if (++total.files > MAX_FILES) throw new Error(`Obsidian vault exceeds ${MAX_FILES} Markdown files`);
    const content = await readFile(file);
    total.bytes += content.byteLength;
    if (total.bytes > MAX_BYTES) throw new Error(`Obsidian vault exceeds ${MAX_BYTES} bytes`);
    const parsed = properties(content.toString("utf8"));
    const issues: string[] = [];
    if (!Object.keys(parsed).length) issues.push("missing YAML properties");
    if (parsed.type === undefined) issues.push("missing property: type");
    notes.push({
      path: path.relative(root, file),
      bytes: content.byteLength,
      sha256: createHash("sha256").update(content).digest("hex"),
      properties: parsed,
      issues,
    });
  }
}

export async function discoverObsidianVault(connection?: ObsidianConnection): Promise<ObsidianDiscovery> {
  const resolvedConnection = connection ?? await loadObsidianConnection();
  await access(resolvedConnection.vaultPath);
  const notes: ObsidianNote[] = [];
  const total = { files: 0, bytes: 0 };
  await collect(resolvedConnection.vaultPath, resolvedConnection.vaultPath, notes, total);
  return {
    vaultPath: resolvedConnection.vaultPath,
    noteCount: notes.length,
    totalBytes: total.bytes,
    notes,
    issues: notes.flatMap((note) => note.issues.map((issue) => `${note.path}: ${issue}`)),
  };
}
