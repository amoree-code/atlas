import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import { buildAtlasResourceInjection } from "../../application/context/resource-injection.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import { findProvider, loadProviderRegistry, resolveOriginalExecutable } from "../../infrastructure/providers/provider-registry.js";
import { enginePath } from "../../paths.js";
import { providerWrapperPath, shimDirectory } from "../../infrastructure/wrappers/wrapper-manager.js";

export async function runClientTestCommand(providerName: string, json = false): Promise<void> {
  const injection = await buildAtlasResourceInjection();
  const cwd = path.resolve(process.cwd());
  const providers = providerName ? [findProvider(providerName)] : loadProviderRegistry();
  const store = await openSessionStore();
  const reports = providers.map((provider) => buildReport(provider, cwd, injection, store));
  store.close();

  if (json) {
    console.log(JSON.stringify(providerName ? reports[0] : reports, null, 2));
    return;
  }
  for (const report of reports) printReport(report);
}

function buildReport(provider: ReturnType<typeof findProvider>, cwd: string, injection: Awaited<ReturnType<typeof buildAtlasResourceInjection>>, store: Awaited<ReturnType<typeof openSessionStore>>) {
  let executable: string | null = null;
  try { executable = resolveOriginalExecutable(provider.command); } catch { /* Report missing provider below. */ }
  const latest = store.list().find((session) => session.provider === provider.id) ?? null;
  const events = latest ? store.listEvents(latest.sessionId) : [];
  const entry = events.find((event) => event.type === "session_entry_contract");
  const manifest = events.find((event) => event.type === "atlas_resource_manifest" || event.type === "context_manifest");
  return {
    provider: provider.id,
    routing: { cwd, command: provider.command, shim: providerWrapperPath(provider.command), shimDirectory: shimDirectory(), nativeExecutable: executable, atlasEngine: enginePath("dist", "main.js") },
    atlas: { root: atlasPath(), files: injection.manifest.files, bytes: injection.manifest.bytes, sessionStore: atlasPath("system", "sessions", "sessions.sqlite"), runtimeLogs: atlasPath("system", "runtime", "logs", "runtime.jsonl"), sessionSummaries: atlasPath("system", "sessions", "summaries") },
    transport: provider.id === "claude" ? { headless: "PROVEN: injected with --append-system-prompt", interactive: "NOT PROVEN: manifest-only" } : { headless: "provider-specific; inspect session", interactive: "provider-specific; inspect session" },
    providerOwnedPaths: provider.id === "claude" ? [path.join(os.homedir(), ".claude"), path.join(os.homedir(), ".claude", "CLAUDE.md"), path.join(cwd, "CLAUDE.md"), path.join(cwd, ".claude", "CLAUDE.md")].map((file) => ({ path: file, exists: existsSync(file) })) : [{ path: "provider-managed (not controlled by Atlas)", exists: null }],
    latestSession: latest ? { sessionId: latest.sessionId, status: latest.status, entryContract: entry ? JSON.parse(entry.data) : null, contextManifest: manifest ? JSON.parse(manifest.data) : null } : null,
  };
}

function printReport(report: ReturnType<typeof buildReport>): void {
  console.log(`Atlas client test: ${report.provider}`);
  console.log(`cwd: ${report.routing.cwd}`);
  console.log(`shim: ${report.routing.shim}`);
  console.log(`native executable: ${report.routing.nativeExecutable ?? "NOT FOUND outside Atlas shims"}`);
  console.log(`Atlas engine: ${report.routing.atlasEngine}`);
  console.log(`Atlas files: ${report.atlas.files.length ? report.atlas.files.join(", ") : "none"}`);
  console.log(`Atlas saves sessions: ${report.atlas.sessionStore}`);
  console.log(`Atlas saves runtime logs: ${report.atlas.runtimeLogs}`);
  console.log(`Atlas saves summaries: ${report.atlas.sessionSummaries}`);
  console.log(`headless: ${report.transport.headless}`);
  console.log(`interactive: ${report.transport.interactive}`);
  console.log("Provider-owned paths:");
  for (const file of report.providerOwnedPaths) console.log(`- ${file.exists === null ? "not controlled" : file.exists ? "present" : "absent"}: ${file.path}`);
  if (report.latestSession) console.log(`latest session: ${report.latestSession.sessionId} [${report.latestSession.status}] — inspect with: atlas session events ${report.latestSession.sessionId}`);
  else console.log("latest session: none");
}
