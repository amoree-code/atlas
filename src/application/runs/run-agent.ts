import { randomUUID } from "node:crypto";
import { buildContext } from "../../infrastructure/filesystem/context-manager.js";
import { loadSkills } from "../../infrastructure/filesystem/skill-loader.js";
import { loadProfile } from "../../infrastructure/filesystem/profile-loader.js";
import { profileIdentity } from "../../domain/profiles/profile.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import type { Session } from "../../domain/sessions/session.js";
import { runProvider, type HeadlessProvider, type ProviderRequest } from "../../infrastructure/providers/providers.js";
import type { HeadlessResult, RuntimeEvent } from "../../infrastructure/process/cli-process.js";
import { appendRuntimeLog } from "../../infrastructure/observability/runtime-logger.js";
import { authorizeRun } from "./run-authorization.js";
import type { RunContract } from "../../domain/runs/run-contract.js";

export type AgentRunRequest = {
  profileName: string;
  prompt: string;
  cwd: string;
  parentSessionId?: string;
  sessionId?: string;
  runContract?: RunContract;
};

export type ProviderExecutor = (request: ProviderRequest) => Promise<HeadlessResult>;

export async function runAgent(request: AgentRunRequest, execute: ProviderExecutor = runProvider): Promise<Session> {
  const profile = await loadProfile(request.profileName);
  const sessionStore = await openSessionStore();
  const sessionId = request.sessionId ?? randomUUID();
  const session = sessionStore.create({
    sessionId,
    provider: profile.provider,
    providerSessionId: null,
    parentSessionId: request.parentSessionId ?? null,
    profile: profile.name,
    profileIdentity: profileIdentity(profile),
    workingDirectory: request.cwd,
    resumeData: null,
  });

  if (request.runContract) {
    if (request.runContract.sessionId !== sessionId) {
      sessionStore.close();
      throw new Error("Run contract session does not match the session being created");
    }
    try { authorizeRun(sessionStore, request.runContract); } catch (error) { sessionStore.close(); throw error; }
  }

  try {
    const context = await buildContext(profile, request.cwd);
    const skills = await loadSkills(profile.skills, 32_000, request.cwd);
    sessionStore.appendEvent(sessionId, "context_manifest", JSON.stringify(context.manifest));
    sessionStore.updateStatus(sessionId, "running");
    const skillContent = skills.map((skill) => `## Skill: ${skill.name}\n${skill.instructions}`).join("\n\n");
    const prompt = [request.prompt, skillContent, context.content].filter(Boolean).join("\n\n");
    const result = await execute({
      provider: profile.provider as HeadlessProvider,
      prompt,
      cwd: request.cwd,
      timeoutMs: request.runContract?.budget.timeoutMs,
      maxOutputBytes: request.runContract?.budget.maxOutputBytes,
      onEvent: (event) => {
        captureProviderSessionId(sessionStore, sessionId, event);
        sessionStore.appendEvent(sessionId, event.type, boundedEventData(event));
      },
    });
    sessionStore.updateStatus(sessionId, result.exitCode === 0 ? "completed" : "failed");
    sessionStore.appendEvent(sessionId, "process_exit", JSON.stringify({ exitCode: result.exitCode, stderr: result.stderr }));
    sessionStore.appendEvent(sessionId, "evidence", JSON.stringify({ evidenceId: randomUUID(), sessionId, type: "provider_exit", source: "headless-process", observedAt: new Date().toISOString(), result: result.exitCode === 0 ? "proven" : "not_proven", criterion: "provider process exits successfully", payload: JSON.stringify({ exitCode: result.exitCode }) }));
    await appendRuntimeLog({ timestamp: new Date().toISOString(), event: result.exitCode === 124 ? "provider_timeout" : "run_finished", correlationId: sessionId, sessionId, provider: profile.provider, status: result.exitCode === 0 ? "completed" : "failed", payload: JSON.stringify({ exitCode: result.exitCode }) });
    return sessionStore.get(sessionId) ?? session;
  } catch (error) {
    sessionStore.updateStatus(sessionId, "failed");
    sessionStore.appendEvent(sessionId, "error", error instanceof Error ? error.message : String(error));
    await appendRuntimeLog({ timestamp: new Date().toISOString(), event: "run_failed", correlationId: sessionId, sessionId, provider: profile.provider, status: "failed" });
    throw error;
  } finally {
    sessionStore.close();
  }
}

export async function resumeAgent(sessionId: string, prompt: string, execute: ProviderExecutor = runProvider): Promise<Session> {
  const sessionStore = await openSessionStore();
  const existing = sessionStore.get(sessionId);
  if (!existing) throw new Error(`Session not found: ${sessionId}`);
  if (existing.provider !== "claude" || !existing.providerSessionId) {
    throw new Error(`Provider does not support resume yet: ${existing.provider}`);
  }

  try {
    sessionStore.updateStatus(sessionId, "running");
    sessionStore.appendEvent(sessionId, "resume_requested", prompt);
    const result = await execute({
      provider: "claude",
      prompt,
      cwd: existing.workingDirectory,
      resumeId: existing.providerSessionId,
      onEvent: (event) => {
        captureProviderSessionId(sessionStore, sessionId, event);
        sessionStore.appendEvent(sessionId, event.type, boundedEventData(event));
      },
    });
    sessionStore.updateStatus(sessionId, result.exitCode === 0 ? "completed" : "failed");
    sessionStore.appendEvent(sessionId, "process_exit", JSON.stringify({ exitCode: result.exitCode, stderr: result.stderr }));
    return sessionStore.get(sessionId) ?? existing;
  } catch (error) {
    sessionStore.updateStatus(sessionId, "failed");
    sessionStore.appendEvent(sessionId, "error", error instanceof Error ? error.message : String(error));
    throw error;
  } finally {
    sessionStore.close();
  }
}

function boundedEventData(event: RuntimeEvent): string {
  const serialized = typeof event.data === "string" ? event.data : JSON.stringify(event.data);
  return serialized.slice(0, 64_000);
}

function captureProviderSessionId(store: Awaited<ReturnType<typeof openSessionStore>>, sessionId: string, event: RuntimeEvent): void {
  if (event.type === "json" && typeof event.data === "object" && event.data !== null && "session_id" in event.data) {
    const providerSessionId = (event.data as { session_id?: unknown }).session_id;
    if (typeof providerSessionId === "string") store.updateProviderSessionId(sessionId, providerSessionId);
  }
}
