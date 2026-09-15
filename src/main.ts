#!/usr/bin/env node
import { runFirstRunWizard, setup } from "./interfaces/cli/setup-command.js";
import { runAgent } from "./application/runs/run-agent.js";
import { resumeAgent } from "./application/runs/run-agent.js";
import { runService } from "./infrastructure/process/service.js";
import { atlasRoot } from "./paths.js";
import { openSessionStore } from "./infrastructure/persistence/session-store.js";
import { intercept } from "./interfaces/cli/intercept-command.js";
import { loadProviderRegistry } from "./infrastructure/providers/provider-registry.js";
import { installShellPath, registerProvider, syncProviderWrappers, wrapperDoctor, wrapperStatus } from "./infrastructure/wrappers/wrapper-manager.js";
import { findInstallSpec, installPlan, installProvider, listInstallSpecs, removeInstalledProvider, updateProvider } from "./application/install/provider-installer.js";
import { runAuthCommand } from "./interfaces/cli/auth-command.js";
import { runTicketsCommand } from "./interfaces/cli/tickets-command.js";
import { runMemoryCommand } from "./interfaces/cli/memory-command.js";
import { runCaptureCommand } from "./interfaces/cli/capture-command.js";
import { runContextCommand } from "./interfaces/cli/context-command.js";
import { hasFailures, repairWorkspace, workspaceReport } from "./application/doctor/workspace-doctor.js";
import { listSchedules, runDueSchedules, runSchedule, runSchedulerWorker, runSchedulerWorkerOnce, saveSchedule, setScheduleEnabled } from "./application/scheduler/local-scheduler.js";
import { createWebhookGateway } from "./application/gateway/webhook-gateway.js";
import { addSkillCandidate, learnSkillFromSession, listSkillCandidates, reviewSkillCandidate } from "./application/skills/skill-curation.js";
import { connectObsidianVault, discoverObsidianVault, loadObsidianConnection } from "./application/obsidian/vault-discovery.js";
import { syncObsidianVault, watchObsidianVault } from "./application/obsidian/vault-sync.js";
import { listInboxCandidates, promoteInboxNote } from "./application/obsidian/inbox-promotion.js";
import { writeObsidianNote } from "./application/obsidian/vault-writer.js";
import { runObsidianMcpServer } from "./infrastructure/mcp/obsidian-server.js";
import { runAtlasMcpServer } from "./infrastructure/mcp/atlas-server.js";
import { atlasMcpConfig } from "./application/mcp/mcp-connection.js";
import { promoteSessionToKnowledge } from "./application/memory/session-promotion.js";
import { runBrowserCommand } from "./interfaces/cli/browser-command.js";
import { configureClaudeCodeWrapper } from "./application/integrations/claude-vscode.js";
import { runHandoffCommand } from "./interfaces/cli/handoff-command.js";
import { runIdeaCommand } from "./interfaces/cli/idea-command.js";
import { runDailyCommand } from "./interfaces/cli/daily-command.js";

const command = process.argv[2] === "--yes" ? undefined : process.argv[2];

if (!command) {
  await runFirstRunWizard(process.argv.includes("--yes"));
} else if (command === "setup") {
  const obsidianIndex = process.argv.indexOf("--obsidian");
  const obsidianPath = obsidianIndex >= 0 ? process.argv[obsidianIndex + 1] : undefined;
  if (obsidianIndex >= 0 && !obsidianPath) {
    console.error("Usage: atlas setup [--obsidian <vault-path>] [--read-write]");
    process.exitCode = 1;
  } else {
    await setup({ obsidianPath, obsidianMode: process.argv.includes("--read-write") ? "read-write" : "read-only" });
  }
} else if (command === "service") {
  const shutdownAfterMs = Number(process.env.ATLAS_SERVICE_TEST_SHUTDOWN_MS);
  await runService(Number.isFinite(shutdownAfterMs) && shutdownAfterMs > 0 ? shutdownAfterMs : undefined);
} else if (command === "intercept") {
  const clientIndex = process.argv.indexOf("--client");
  const executableIndex = process.argv.indexOf("--executable");
  const separatorIndex = process.argv.indexOf("--");
  const client = clientIndex >= 0 ? process.argv[clientIndex + 1] : "";
  const args = separatorIndex >= 0 ? process.argv.slice(separatorIndex + 1) : [];
  if (!client) {
    console.error("Usage: atlas intercept --client <provider> -- [args]");
    process.exitCode = 1;
  } else {
    process.exitCode = await intercept(client, args, executableIndex >= 0
      ? { originalExecutable: process.argv[executableIndex + 1], entryPoint: "desktop-wrapper", controlLevel: "managed-partial" }
      : undefined);
  }
} else if (command === "client") {
  const action = process.argv[3] ?? "list";
  if (action === "list") {
    console.log(JSON.stringify(loadProviderRegistry(), null, 2));
  } else if (action === "open") {
    const provider = process.argv[4];
    if (!provider) {
      console.error("Usage: atlas client open <provider> [provider-args]");
      process.exitCode = 1;
    } else {
      const providerArgs = process.argv.slice(5);
      const ticketIndex = providerArgs.indexOf("--ticket");
      const handoffIndex = providerArgs.indexOf("--handoff");
      const ticketId = ticketIndex >= 0 ? providerArgs[ticketIndex + 1] : undefined;
      const handoffId = handoffIndex >= 0 ? providerArgs[handoffIndex + 1] : undefined;
      const metadataFlags = new Set<number>();
      if (ticketIndex >= 0) { metadataFlags.add(ticketIndex); metadataFlags.add(ticketIndex + 1); }
      if (handoffIndex >= 0) { metadataFlags.add(handoffIndex); metadataFlags.add(handoffIndex + 1); }
      process.exitCode = await intercept(provider, providerArgs.filter((_, index) => !metadataFlags.has(index)), {
        entryPoint: "interactive-managed", controlLevel: "managed-partial", ticketId, handoffId,
      });
    }
  } else if (action === "sync") {
    const result = await syncProviderWrappers();
    console.log(JSON.stringify({ directory: result.directory, providers: result.providers }, null, 2));
  } else if (action === "register") {
    const id = process.argv[4];
    const provider = await registerProvider(id ?? "", process.argv[5] ?? id ?? "");
    console.log(JSON.stringify(provider, null, 2));
  } else if (action === "doctor") {
    const findings = await wrapperDoctor(process.argv[4]);
    if (findings.length) {
      findings.forEach((finding) => console.error(`NOT READY: ${finding}`));
      process.exitCode = 1;
    } else {
      console.log("PROVEN: Atlas wrappers are configured and provider binaries resolve outside the shim directory.");
    }
  } else if (action === "status") {
    console.log(JSON.stringify(await wrapperStatus(), null, 2));
  } else if (action === "vscode-wrapper") {
    const settingsIndex = process.argv.indexOf("--settings");
    const settingsPath = settingsIndex >= 0 ? process.argv[settingsIndex + 1] : undefined;
    console.log(JSON.stringify(await configureClaudeCodeWrapper(settingsPath, process.argv.includes("--apply")), null, 2));
  } else {
    console.error("Usage: atlas client list|status|open <provider> [provider-args]|vscode-wrapper [--settings <path>] [--apply]|sync|register <id> [command]|doctor [absolute-provider-path]");
    process.exitCode = 1;
  }
} else if (command === "install") {
  const id = process.argv[3];
  if (!id) {
    console.error("Usage: atlas install <client> [--yes]");
    process.exitCode = 1;
  } else {
    try {
      const spec = findInstallSpec(id);
      if (!process.argv.includes("--yes")) {
        console.log(JSON.stringify({ approvalRequired: true, plan: installPlan(spec.provider.id) }, null, 2));
        process.exitCode = 2;
      } else {
        const result = await installProvider(spec.provider.id, true);
        console.log(JSON.stringify({ installed: true, provider: result.provider, executable: result.executable }, null, 2));
      }
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
} else if (command === "auth") {
  await runAuthCommand(process.argv[3] ?? "", process.argv[4] ?? "");
} else if (command === "tickets") {
  await runTicketsCommand(process.argv[3] ?? "", process.argv.slice(4));
} else if (command === "memory") {
  await runMemoryCommand(process.argv[3] ?? "", process.argv.slice(4));
} else if (command === "mcp") {
  const action = process.argv[3] ?? "config";
  if (action === "config") console.log(JSON.stringify(atlasMcpConfig(), null, 2));
  else if (action === "serve") await runAtlasMcpServer();
  else { console.error("Usage: atlas mcp config|serve"); process.exitCode = 1; }
} else if (command === "obsidian") {
  const action = process.argv[3] ?? "discover";
  if (action === "mcp") await runObsidianMcpServer();
  else if (!["connect", "discover", "sync", "watch", "inbox", "write"].includes(action)) {
    console.error("Usage: atlas obsidian connect <vault-path> [--read-write]|discover|sync|watch|inbox|write");
    process.exitCode = 1;
  } else {
    try {
      if (action === "connect") {
        const vaultPath = process.argv[4];
        if (!vaultPath) throw new Error("Usage: atlas obsidian connect <vault-path> [--read-write]");
        const readWrite = process.argv.includes("--read-write");
        const mode = readWrite ? "read-write" as const : "read-only" as const;
        const result = await connectObsidianVault(vaultPath, mode);
        const synced = await syncObsidianVault(await loadObsidianConnection());
        console.log(JSON.stringify({ connected: true, mode, vaultPath: result.vaultPath, noteCount: synced.noteCount, added: synced.added, changed: synced.changed, removed: synced.removed, issues: synced.issues }, null, 2));
      } else {
        const connection = await loadObsidianConnection();
        if (action === "write") {
        const relative = process.argv[4];
        const content = process.argv[5];
        const expectedSha256 = process.argv[6] ?? null;
        if (!relative || content === undefined) throw new Error("Usage: atlas obsidian write <relative.md> <content> [expected-sha256] [--apply]");
        console.log(JSON.stringify(await writeObsidianNote(connection, relative, content, expectedSha256 === "-" ? null : expectedSha256, process.argv.includes("--apply")), null, 2));
        } else if (action === "inbox") {
        const inboxAction = process.argv[4] ?? "list";
        if (inboxAction === "list") console.log(JSON.stringify(await listInboxCandidates(connection), null, 2));
        else if (inboxAction === "promote") {
          const source = process.argv[5];
          const target = process.argv[6];
          if (!source || !target) throw new Error("Usage: atlas obsidian inbox promote <source.md> <target-directory> [--apply]");
          console.log(JSON.stringify(await promoteInboxNote(connection, source, target, process.argv.includes("--apply")), null, 2));
        } else throw new Error("Usage: atlas obsidian inbox list|promote <source.md> <target-directory> [--apply]");
        } else if (action === "discover") console.log(JSON.stringify(await discoverObsidianVault(connection), null, 2));
        else if (action === "sync") console.log(JSON.stringify(await syncObsidianVault(connection), null, 2));
        else {
        const controller = new AbortController();
        process.once("SIGINT", () => controller.abort());
        process.once("SIGTERM", () => controller.abort());
        await watchObsidianVault(connection, undefined, controller.signal);
        }
      }
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
} else if (command === "capture") {
  await runCaptureCommand(process.argv[3] ?? "", process.argv.slice(4));
} else if (command === "handoff") {
  try { await runHandoffCommand(process.argv[3] ?? "list", process.argv.slice(4)); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
} else if (command === "context") {
  await runContextCommand(process.argv.includes("--json"));
} else if (command === "idea") {
  try { await runIdeaCommand(process.argv[3] ?? "list", process.argv.slice(4)); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
} else if (command === "daily") {
  try { await runDailyCommand(process.argv[3] ?? "start", process.argv.slice(4)); }
  catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
} else if (command === "schedule") {
  const action = process.argv[3] ?? "list";
  if (action === "list") console.log(JSON.stringify(await listSchedules(), null, 2));
  else if (action === "add") {
    const [id, profile, intervalMs, ...prompt] = process.argv.slice(4);
    if (!id || !profile || !intervalMs || !prompt.length) { console.error("Usage: atlas schedule add <id> <profile> <interval-ms> <prompt>"); process.exitCode = 1; }
    else await saveSchedule({ id, profile, prompt: prompt.join(" "), intervalMs: Number(intervalMs), nextRunAt: new Date().toISOString(), enabled: true });
  } else if (action === "run-due") console.log(JSON.stringify({ ran: await runDueSchedules(atlasRoot()) }, null, 2));
  else if (action === "worker-once") console.log(JSON.stringify({ ran: await runSchedulerWorkerOnce(atlasRoot()) }, null, 2));
  else if (action === "worker") {
    const controller = new AbortController();
    const stop = () => controller.abort(); process.once("SIGINT", stop); process.once("SIGTERM", stop);
    await runSchedulerWorker(atlasRoot(), { signal: controller.signal, pollMs: Number(process.env.ATLAS_SCHEDULER_POLL_MS ?? 30_000) });
    process.off("SIGINT", stop); process.off("SIGTERM", stop);
  }
  else if (action === "enable" || action === "disable") console.log(JSON.stringify(await setScheduleEnabled(process.argv[4] ?? "", action === "enable"), null, 2));
  else if (action === "run-now") await runSchedule(process.argv[4] ?? "", atlasRoot());
  else { console.error("Usage: atlas schedule list|add|enable|disable|run-due|run-now|worker-once|worker"); process.exitCode = 1; }
} else if (command === "gateway") {
  const port = Number(process.env.ATLAS_GATEWAY_PORT ?? 8787);
  const token = process.env.ATLAS_GATEWAY_TOKEN;
  if (!token) { console.error("ATLAS_GATEWAY_TOKEN is required"); process.exitCode = 1; }
  else {
    const server = createWebhookGateway(atlasRoot(), token);
    server.listen(port, "127.0.0.1", () => console.log(`Atlas webhook gateway listening on 127.0.0.1:${port}`));
  }
} else if (command === "skill") {
  const action = process.argv[3] ?? "list";
  if (action === "list") console.log(JSON.stringify(await listSkillCandidates(), null, 2));
  else if (action === "add") {
    const [id, name, ...instructions] = process.argv.slice(4);
    if (!id || !name || !instructions.length) { console.error("Usage: atlas skill add <id> <name> <instructions>"); process.exitCode = 1; }
    else console.log(JSON.stringify(await addSkillCandidate({ id, name, instructions: instructions.join(" ") }), null, 2));
  } else if (action === "review") {
    const [id, status] = process.argv.slice(4);
    if (!id || (status !== "promoted" && status !== "rejected")) { console.error("Usage: atlas skill review <id> promoted|rejected"); process.exitCode = 1; }
    else console.log(JSON.stringify(await reviewSkillCandidate(id, status), null, 2));
  } else if (action === "learn") {
    const sessionId = process.argv[4];
    if (!sessionId) { console.error("Usage: atlas skill learn <completed-session-id>"); process.exitCode = 1; }
    else console.log(JSON.stringify(await learnSkillFromSession(sessionId), null, 2));
  } else { console.error("Usage: atlas skill list|add|learn|review"); process.exitCode = 1; }
} else if (command === "catalog") {
  console.log(JSON.stringify(listInstallSpecs().map((spec) => ({ id: spec.provider.id, command: spec.provider.command, installer: installPlan(spec.provider.id) })), null, 2));
} else if (command === "env") {
  console.log(await installShellPath());
} else if (command === "update" || command === "remove") {
  const id = process.argv[3];
  if (!id || !process.argv.includes("--yes")) {
    console.error(`Usage: atlas ${command} <client> --yes`);
    process.exitCode = 2;
  } else {
    try {
      const result = command === "update"
        ? await updateProvider(id, true)
        : await removeInstalledProvider(id, true);
      console.log(JSON.stringify({ [command === "update" ? "updated" : "removed"]: true, provider: result }, null, 2));
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
} else if (command === "doctor") {
  const report = await workspaceReport();
  if (process.argv.includes("--json")) console.log(JSON.stringify(report, null, 2));
  else report.findings.forEach((finding) => console.log(`${finding.severity}: ${finding.code} — ${finding.message}`));
  if (hasFailures(report.findings)) process.exitCode = 1;
} else if (command === "repair") {
  const apply = process.argv.includes("--apply");
  if (!apply) {
    const report = await workspaceReport();
    console.log(JSON.stringify({ dryRun: true, fixable: report.findings.filter((finding) => finding.fixable), findings: report.findings }, null, 2));
  } else {
    const result = await repairWorkspace();
    console.log(JSON.stringify({ applied: result.changes, findings: result.findings }, null, 2));
    if (hasFailures(result.findings)) process.exitCode = 1;
  }
} else if (command === "browser") {
  await runBrowserCommand(process.argv[3] ?? "", process.argv.slice(4));
} else if (command === "run") {
  const profileIndex = process.argv.indexOf("--profile");
  const promptIndex = process.argv.indexOf("--prompt");
  const clientIndex = process.argv.indexOf("--client");
  const ticketIndex = process.argv.indexOf("--ticket");
  const handoffIndex = process.argv.indexOf("--handoff");
  const profileName = profileIndex >= 0 ? process.argv[profileIndex + 1] : "default";
  const client = clientIndex >= 0 ? process.argv[clientIndex + 1] : undefined;
  const ticketId = ticketIndex >= 0 ? process.argv[ticketIndex + 1] : undefined;
  const handoffId = handoffIndex >= 0 ? process.argv[handoffIndex + 1] : undefined;
  const prompt = promptIndex >= 0 ? process.argv.slice(promptIndex + 1).join(" ") : "";
  if (!profileName || !prompt) {
    console.error("Usage: atlas run --profile <name> [--client <client>] [--ticket <id>] [--handoff <id>] --prompt <text>");
    process.exitCode = 1;
  } else {
    const session = await runAgent({ profileName, client, ticketId, handoffId, prompt, cwd: atlasRoot() });
    console.log(JSON.stringify({ sessionId: session.sessionId, status: session.status }));
  }
} else if (command === "session") {
  const action = process.argv[3] ?? "list";
  const store = await openSessionStore();
  if (action === "list") {
    console.log(JSON.stringify(store.list()));
    store.close();
  } else if (action === "show") {
    const sessionId = process.argv[4] ?? "";
    const session = store.get(sessionId);
    const entryEvent = session ? store.listEvents(sessionId).find((event) => event.type === "session_entry_contract") : undefined;
    store.close();
    if (!session) { console.error("Session not found"); process.exitCode = 1; }
    else console.log(JSON.stringify({ ...session, entryContract: entryEvent ? JSON.parse(entryEvent.data) : null }));
  } else if (action === "events") {
    const sessionId = process.argv[4] ?? "";
    const session = store.get(sessionId);
    const events = session ? store.listEvents(sessionId) : [];
    store.close();
    if (!session) { console.error("Session not found"); process.exitCode = 1; }
    else console.log(JSON.stringify(events, null, 2));
  } else if (action === "resume") {
    const sessionId = process.argv[4];
    const prompt = process.argv.slice(5).join(" ");
    store.close();
    if (!sessionId || !prompt) {
      console.error("Usage: atlas session resume <session-id> <prompt>");
      process.exitCode = 1;
    } else {
      const session = await resumeAgent(sessionId, prompt);
      console.log(JSON.stringify({ sessionId: session.sessionId, status: session.status }));
    }
  } else if (action === "promote") {
    const sessionId = process.argv[4];
    const target = process.argv[5] ?? "knowledge/results";
    store.close();
    if (!sessionId) {
      console.error("Usage: atlas session promote <session-id> [knowledge/<kind>] --approve");
      process.exitCode = 1;
    } else {
      try { console.log(JSON.stringify(await promoteSessionToKnowledge(sessionId, target, process.argv.includes("--approve")), null, 2)); }
      catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exitCode = 1; }
    }
  } else if (action === "doctor") {
    const thresholdHours = Number(process.argv[4] ?? "24");
    const apply = process.argv.includes("--apply");
    if (!Number.isFinite(thresholdHours) || thresholdHours <= 0) {
      store.close();
      console.error("Usage: atlas session doctor [hours] [--apply]");
      process.exitCode = 1;
    } else {
      const thresholdMs = thresholdHours * 60 * 60 * 1000;
      const stale = apply ? store.reconcileStaleRunning(thresholdMs) : store.listStaleRunning(thresholdMs);
      console.log(JSON.stringify({ apply, thresholdHours, stale: stale.map((session) => ({ sessionId: session.sessionId, provider: session.provider, updatedAt: session.updatedAt })), integrity: store.integrityCheck() }));
      store.close();
    }
  } else {
    store.close();
    console.error("Usage: atlas session list|show <session-id>|events <session-id>|resume <session-id> <prompt>|promote <session-id> [knowledge/<kind>] --approve|doctor [hours] [--apply]");
    process.exitCode = 1;
  }
} else {
  console.error(`Unknown command: ${command}`);
  process.exitCode = 1;
}
