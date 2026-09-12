import { randomUUID } from "node:crypto";
import path from "node:path";
import { appendSessionSummary } from "../../application/memory/session-summary.js";
import { profileIdentity, type Profile } from "../../domain/profiles/profile.js";
import { validateRunContract } from "../../domain/runs/run-contract.js";
import { authorizeRun } from "../../application/runs/run-authorization.js";
import { runInteractive } from "../../infrastructure/process/interactive-process.js";
import { findProvider, resolveOriginalExecutable } from "../../infrastructure/providers/provider-registry.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import { applyProviderResourceAdapter, buildAtlasResourceInjection, resourceEnvironment } from "../../application/context/resource-injection.js";
import { redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { OpenShellRuntime } from "../../infrastructure/sandbox/openshell-runtime.js";
import { authAdapter, authLogin, authStatus } from "../../application/auth/auth-orchestrator.js";

export async function intercept(command: string, args: string[]): Promise<number> {
  const provider = findProvider(command);
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
    provider: provider.id,
    providerSessionId: null,
    parentSessionId: null,
    profile: profile.name,
    profileIdentity: profileIdentity(profile),
    workingDirectory,
    resumeData: null,
  });
  store.appendEvent(sessionId, "intercept_requested", JSON.stringify({ runId, command: provider.command, args: args.map(redactRuntimeText) }));
  store.appendEvent(sessionId, "atlas_resource_manifest", JSON.stringify({
    provider: provider.id,
    ...resourceInjection.manifest,
    adapter: { transport: resourceAdapter.transport, consumesContent: resourceAdapter.consumesContent },
  }));

  try {
    store.updateStatus(sessionId, "running");
    authorizeRun(store, contract);
    const executable = resolveOriginalExecutable(provider.command);
    const sandboxEnabled = process.env.ATLAS_SANDBOX_RUNTIME === "openshell";
    if (sandboxEnabled) {
      store.appendEvent(sessionId, "auth_deferred", JSON.stringify({ provider: provider.id, reason: "sandbox-first execution has no credential attachment" }));
    } else {
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
    }
    store.appendEvent(sessionId, "provider_resolved", JSON.stringify({ executable, runtime: sandboxEnabled ? "openshell" : "direct" }));
    const processRequest = {
      command: provider.command,
      args: resourceAdapter.args,
      cwd: workingDirectory,
      environment: {
        ATLAS_INTERCEPTED: "1",
        ...(process.env.ATLAS_OPENSHELL_AUTO_PROVIDERS === "1" ? { ATLAS_OPENSHELL_AUTO_PROVIDERS: "1" } : {}),
        ...resourceEnvironment(provider.id, resourceInjection),
      },
    };
    const runProvider = async () => sandboxEnabled
      ? await new OpenShellRuntime().launchInteractive(processRequest)
      : await runInteractive({
          command: executable,
          args: resourceAdapter.args,
          cwd: workingDirectory,
          env: processRequest.environment,
          onData: (data) => store.appendEvent(sessionId, "provider_output", redactRuntimeText(data)),
        });
    let result = await runProvider();
    if (sandboxEnabled && result.output) store.appendEvent(sessionId, "provider_output", redactRuntimeText(result.output));
    let evidence = classifyProviderResult(result.exitCode, result.output);
    if (evidence.result === "blocked_by_client_authentication" && !sandboxEnabled && authAdapter(provider.id)) {
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
  };
}
