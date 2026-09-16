import { readFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import { appendConflict, contentHash } from "./conflict-log.js";
import type { ObsidianConnection } from "./vault-discovery.js";
import type { ObsidianSyncResult } from "./vault-sync.js";

export type VaultIngestionResult = {
  inbox: string[];
  promotionCandidates: string[];
  conflicts: string[];
  removed: string[];
};

function isInbox(file: string): boolean { return file === "00-Inbox" || file.startsWith("00-Inbox/"); }
function isPromotionArea(file: string): boolean {
  return ["02-Areas/", "03-Resources/", "05-Goals/"].some((root) => file.startsWith(root));
}
function isAtlasProject(file: string): boolean { return file.startsWith("01-Projects/Atlas/") || file === "01-Projects/Atlas.md"; }

async function readOptional(file: string): Promise<string | undefined> {
  try { return await readFile(file, "utf8"); }
  catch (error) { if ((error as NodeJS.ErrnoException).code === "ENOENT") return undefined; throw error; }
}

export async function ingestVaultChanges(connection: ObsidianConnection, result: ObsidianSyncResult, stateFile?: string, baselineState?: Record<string, { sha256: string }>): Promise<VaultIngestionResult> {
  const state = stateFile ? JSON.parse(await readFile(stateFile, "utf8")) as { notes?: Record<string, { sha256: string }> } : { notes: baselineState ?? {} };
  const baseline = state.notes ?? {};
  const changed = [...result.added, ...result.changed];
  const output: VaultIngestionResult = { inbox: [], promotionCandidates: [], conflicts: [], removed: [...result.removed] };
  for (const relative of changed) {
    if (isInbox(relative)) { output.inbox.push(relative); continue; }
    if (isPromotionArea(relative)) { output.promotionCandidates.push(relative); continue; }
    if (!isAtlasProject(relative)) continue;
    const vaultContent = await readOptional(path.join(connection.vaultPath, relative));
    const atlasRelative = relative === "01-Projects/Atlas.md" ? "README.md" : relative.slice("01-Projects/Atlas/".length);
    const atlasFile = atlasPath("projects", "atlas", atlasRelative);
    const atlasContent = await readOptional(atlasFile);
    const record = await appendConflict({
      path: relative,
      baselineSha256: baseline[relative]?.sha256 ?? null,
      vaultSha256: contentHash(vaultContent),
      atlasSha256: contentHash(atlasContent),
      vaultContent,
      atlasContent,
      source: "vault-ingestion",
    });
    output.conflicts.push(record);
  }
  return output;
}
