import { readFile, writeFile } from "node:fs/promises";
import { atlasPath } from "../../paths.js";
import { discoverObsidianVault, type ObsidianConnection, type ObsidianDiscovery } from "./vault-discovery.js";

type SyncEntry = { sha256: string; bytes: number };
type SyncState = Record<string, SyncEntry>;

export type ObsidianSyncResult = ObsidianDiscovery & {
  added: string[];
  changed: string[];
  removed: string[];
};

const defaultStatePath = (): string => atlasPath("system", "integrations", "obsidian", "sync-state.json");

async function readState(file: string): Promise<SyncState> {
  try {
    const state = JSON.parse(await readFile(file, "utf8")) as Record<string, unknown>;
    return state.notes && typeof state.notes === "object" ? state.notes as SyncState : state as SyncState;
  }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return {}; throw error; }
}

export async function syncObsidianVault(connection: ObsidianConnection, stateFile = defaultStatePath()): Promise<ObsidianSyncResult> {
  const discovery = await discoverObsidianVault(connection);
  const previous = await readState(stateFile);
  const current = Object.fromEntries(discovery.notes.map((note) => [note.path, { sha256: note.sha256, bytes: note.bytes }]));
  const added = Object.keys(current).filter((file) => !previous[file]);
  const changed = Object.keys(current).filter((file) => previous[file] && previous[file]?.sha256 !== current[file]?.sha256);
  const removed = Object.keys(previous).filter((file) => !current[file]);
  await writeFile(stateFile, `${JSON.stringify({ version: 1, vaultPath: connection.vaultPath, notes: current }, null, 2)}\n`);
  return { ...discovery, added, changed, removed };
}

export async function watchObsidianVault(
  connection: ObsidianConnection,
  stateFile = defaultStatePath(),
  signal?: AbortSignal,
  debounceMs = 250,
): Promise<void> {
  await syncObsidianVault(connection, stateFile);
  const watcher = (await import("node:fs")).watch(connection.vaultPath, { recursive: true });
  let timer: ReturnType<typeof setTimeout> | undefined;
  let running = Promise.resolve();
  const run = (): void => {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      running = running.then(() => syncObsidianVault(connection, stateFile)).then(() => undefined);
    }, debounceMs);
  };
  watcher.on("change", run);
  watcher.on("rename", run);
  await new Promise<void>((resolve) => {
    const stop = (): void => {
      if (timer) clearTimeout(timer);
      watcher.close();
      void running.finally(resolve);
    };
    if (signal?.aborted) stop();
    else signal?.addEventListener("abort", stop, { once: true });
  });
}
