import { randomUUID } from "node:crypto";
import path from "node:path";
import { appendSessionSummary } from "../../application/memory/session-summary.js";
import { profileIdentity, type Profile } from "../../domain/profiles/profile.js";
import { validateRunContract } from "../../domain/runs/run-contract.js";
import { authorizeRun } from "../../application/runs/run-authorization.js";
import { runInteractive, runPassthrough } from "../../infrastructure/process/interactive-process.js";
import { findProvider, resolveOriginalExecutable, validateExplicitExecutable } from "../../infrastructure/providers/provider-registry.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import { applyProviderResourceAdapter, buildAtlasResourceInjection, resourceEnvironment } from "../../application/context/resource-injection.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { authAdapter, authLogin, authStatus } from "../../application/auth/auth-orchestrator.js";
import { validateSessionEntryContract } from "../../domain/sessions/entry-contract.js";

export type InterceptOptions = {
  entryPoint?: "terminal-shim" | "interactive-managed" | "desktop-wrapper";
  controlLevel?: "observed" | "managed-partial";
  originalExecutable?: string;
  title?: string;
  ticketId?: string;
  handoffId?: string;
};

export async function intercept(command: string, args: string[], options: InterceptOptions = {}): Promise<number> {
  const provider = findProvider(command);
  const entryPoint = options.entryPoint ?? (options.originalExecutable ? "desktop-wrapper" : "terminal-shim");
  const controlLevel = options.controlLevel ?? (options.originalExecutable ? "managed-partial" : "observed");
  const inputCapture = options.originalExecutable ? "none" : "bounded-terminal";
  const sessionId = randomUUID();
  const profile = interceptedProfile(provider.id);
  const store = await openSessionStore();
  const resourceInjection = await buildAtlasResourceInjection();
  const resourceAdapter = applyProviderResourceAdapter(provider.id, args, resourceInjection);
  const workingDirectory = path.resolve(process.cwd());
  const runId = randomUUID();
  const contract = validateRunContract({
    runId,
    sessionId,
    profile: profile.name,
    workingDirectory,
    allowedTools: [provider.command],
    deniedTools: [],
    stopConditions: ["provider-process-exits"],
    approval: { required: false, approved: true },
    budget: { timeoutMs: 24 * 60 * 60 * 1000, maxAttempts: 1, maxOutputBytes: 64_000 },
  });

  store.create({
    sessionId,
    title: options.title ?? `${provider.id} session`,
    ticketId: options.ticketId ?? null,
    handoffId: options.handoffId ?? null,
    provider: provider.id,
    providerSessionId: null,
    parentSessionId: null,
    profile: profile.name,
    profileIdentity: profileIdentity(profile),
    workingDirectory,
    resumeData: null,
  });
  store.appendEvent(sessionId, "session_entry_contract", JSON.stringify(validateSessionEntryContract({
    entryPoint,
    controlLevel,
    inputCapture,
    contextTransport: options.originalExecutable ? "desktop-passthrough" : resourceAdapter.transport,
    policyEnforcement: "shim-lifecycle-and-provider-owned-policy",
    promotion: "explicit-review",
    resume: provider.id === "claude" ? "provider-owned-if-exposed" : "unsupported",
  })));
  store.appendEvent(sessionId, "intercept_requested", JSON.stringify({ runId, command: provider.command, args: args.map(redactRuntimeText) }));
  if (options.handoffId) store.appendEvent(sessionId, "handoff_bound", JSON.stringify({ handoffId: options.handoffId, ticketId: options.ticketId ?? null }));
  store.appendEvent(sessionId, "atlas_resource_manifest", JSON.stringify({
    provider: provider.id,
    ...resourceInjection.manifest,
    adapter: { transport: resourceAdapter.transport, consumesContent: resourceAdapter.consumesContent },
  }));

  try {
    store.updateStatus(sessionId, "running");
    authorizeRun(store, contract);
    const executable = options.originalExecutable ? validateExplicitExecutable(options.originalExecutable) : resolveOriginalExecutable(provider.command);
    const authState = await authStatus(provider.id);
    store.appendEvent(sessionId, "auth_state", JSON.stringify({ provider: provider.id, state: authState }));
    if (authState === "login_required") {
      store.appendEvent(sessionId, "auth_login_started", JSON.stringify({ provider: provider.id }));
      const verifiedState = await authLogin(provider.id);
      store.appendEvent(sessionId, "auth_state", JSON.stringify({ provider: provider.id, state: verifiedState }));
      if (verifiedState !== "authenticated") {
        store.updateStatus(sessionId, "failed");
        store.appendEvent(sessionId, "evidence", JSON.stringify({
          sessionId,
          type: "auth",
          source: "atlas-interceptor",
          result: "blocked_by_client_authentication",
          criterion: "provider login did not verify successfully",
        }));
        await appendSessionSummary({ sessionId, provider: provider.id, status: "failed", exitCode: 1 });
        return 1;
      }
    }
    store.appendEvent(sessionId, "provider_resolved", JSON.stringify({ executable, runtime: "direct" }));
    const processRequest = {
      command: provider.command,
      args: resourceAdapter.args,
      cwd: workingDirectory,
      environment: {
        ATLAS_INTERCEPTED: "1",
        ...resourceEnvironment(provider.id, resourceInjection),
      },
    };
    const runProvider = async () => await (options.originalExecutable ? runPassthrough : runInteractive)({
      command: executable,
      args: resourceAdapter.args,
      cwd: workingDirectory,
      env: processRequest.environment,
      onData: (data) => store.appendEvent(sessionId, "provider_output", redactRuntimeText(data)),
      onInput: (data) => store.appendEvent(sessionId, "terminal_input", redactRuntimeText(data)),
    });
    let result = await runProvider();
    let evidence = classifyProviderResult(result.exitCode, result.output);
    if (evidence.result === "blocked_by_client_authentication" && authAdapter(provider.id)) {
      store.appendEvent(sessionId, "auth_recovery_started", JSON.stringify({ provider: provider.id, reason: evidence.criterion }));
      const recoveredState = await authLogin(provider.id);
      store.appendEvent(sessionId, "auth_state", JSON.stringify({ provider: provider.id, state: recoveredState, phase: "recovery" }));
      if (recoveredState === "authenticated") {
        store.appendEvent(sessionId, "run_resumed", JSON.stringify({ provider: provider.id, reason: "authentication verified" }));
        result = await runProvider();
        if (result.output) store.appendEvent(sessionId, "provider_output", redactRuntimeText(result.output));
        evidence = classifyProviderResult(result.exitCode, result.output);
      }
    }
    const status = result.exitCode === 0 ? "completed" : "failed";
    store.updateStatus(sessionId, status);
    store.appendEvent(sessionId, "process_exit", JSON.stringify({ exitCode: result.exitCode }));
    if (evidence.result === "blocked_by_client_authentication") {
      store.appendEvent(sessionId, "provider_blocked", JSON.stringify({ reason: evidence.criterion }));
    }
    store.appendEvent(sessionId, "evidence", JSON.stringify({
      sessionId,
      type: "provider_exit",
      source: "atlas-interceptor",
      result: evidence.result,
      criterion: evidence.criterion,
    }));
    store.scanCaptureItems(sessionId);
    await appendSessionSummary({ sessionId, provider: provider.id, status, exitCode: result.exitCode });
    return result.exitCode;
  } catch (error) {
    store.updateStatus(sessionId, "failed");
    store.appendEvent(sessionId, "error", redactRuntimeText(error instanceof Error ? error.message : String(error)));
    await appendSessionSummary({ sessionId, provider: provider.id, status: "failed", exitCode: 1 });
    throw error;
  } finally {
    store.close();
  }
}

function classifyProviderResult(exitCode: number, output: string): { result: string; criterion: string } {
  if (exitCode === 0) return { result: "proven", criterion: "intercepted provider process exits successfully" };
  if (/401\s+Unauthorized|missing bearer|not logged in|sign in to use/i.test(output)) {
    return { result: "blocked_by_client_authentication", criterion: "provider authentication is required" };
  }
  return { result: "not_proven", criterion: "intercepted provider process exits successfully" };
}

function interceptedProfile(provider: string): Profile {
  return {
    name: `intercepted:${provider}`,
    description: "Atlas transparent CLI interception profile",
    version: "1.0.0",
    provider: provider as Profile["provider"],
    model: "provider-managed",
    role: "intercepted worker",
    skills: [],
    allowedPaths: ["."],
    allowedCommands: [],
    writePolicy: "none",
    contextSources: [],
    clients: { [provider]: { enabled: true, capabilities: [], limitations: [] } },
    defaultClient: provider as Profile["provider"],
    memory: { enabled: true, scope: "profile" },
    verification: { commands: [] },
    instructions: "",
  };
}
