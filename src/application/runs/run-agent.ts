import { createHash, randomUUID } from "node:crypto";
import { buildContext } from "../../infrastructure/filesystem/context-manager.js";
import { loadSkills } from "../../infrastructure/filesystem/skill-loader.js";
import { loadPromotedSkills } from "../skills/skill-curation.js";
import { loadProfile } from "../../infrastructure/filesystem/profile-loader.js";
import { profileIdentity, selectProfileClient } from "../../domain/profiles/profile.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import type { Session } from "../../domain/sessions/session.js";
import { runProvider, type HeadlessProvider, type ProviderRequest } from "../../infrastructure/providers/providers.js";
import type { HeadlessResult, RuntimeEvent } from "../../infrastructure/process/cli-process.js";
import { appendRuntimeLog, redactRuntimeText } from "../../infrastructure/observability/runtime-logger.js";
import { finalizeSession } from "../memory/session-closeout.js";
import { getHandoff } from "../handoff/handoff-service.js";
import { authorizeRun } from "./run-authorization.js";
import type { RunContract } from "../../domain/runs/run-contract.js";
import { executionPolicy } from "../../domain/profiles/profile-policy.js";
import { formatProfileFacts, readProfileFacts } from "../memory/profile-facts.js";
import { emitHook } from "../hooks/lifecycle-hooks.js";
import { resolveClientHome } from "../../infrastructure/providers/client-home.js";
import { validateSessionEntryContract } from "../../domain/sessions/entry-contract.js";

export type AgentRunRequest = {
  profileName: string;
  prompt: string;
  cwd: string;
  parentSessionId?: string;
  sessionId?: string;
  runContract?: RunContract;
  client?: string;
  actor?: string;
  title?: string;
  ticketId?: string;
  handoffId?: string;
};

export type ProviderExecutor = (request: ProviderRequest) => Promise<HeadlessResult>;

export async function runAgent(request: AgentRunRequest, execute: ProviderExecutor = runProvider): Promise<Session> {
  const profile = selectProfileClient(await loadProfile(request.profileName), request.client);
  const handoff = request.handoffId ? await getHandoff(request.handoffId) : null;
  const effectiveTicketId = request.ticketId ?? (typeof handoff?.ticketId === "string" ? handoff.ticketId : null);
  const clientHome = resolveClientHome(profile);
  executionPolicy(profile, request.cwd);
  if (profile.writePolicy !== "none") {
    throw new Error("Writable profile runs require an enforcing sandbox; direct execution cannot enforce writePolicy");
  }
  const sessionStore = await openSessionStore();
  const sessionId = request.sessionId ?? randomUUID();
  const session = sessionStore.create({
    sessionId,
    title: request.title ?? (typeof handoff?.title === "string" ? handoff.title : request.prompt.slice(0, 120)),
    ticketId: effectiveTicketId,
    handoffId: request.handoffId ?? null,
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
    sessionStore.appendEvent(sessionId, "session_entry_contract", JSON.stringify(validateSessionEntryContract({
      entryPoint: "atlas-run",
      controlLevel: "full-head",
      inputCapture: "semantic",
      contextTransport: "profile-context-and-provider-adapter",
      policyEnforcement: "profile-and-run-contract",
      promotion: "explicit-review",
      resume: profile.provider === "claude" ? "provider-session-id" : "unsupported",
    })));
    const context = await buildContext(profile, request.cwd, 32_000, { compression: profile.contextCompression });
    const profileFacts = await readProfileFacts(profile.name);
    const skills = await loadSkills(profile.skills, 32_000, request.cwd);
    const autoSkills = await loadPromotedSkills(request.prompt, Math.max(0, 32_000 - skills.reduce((bytes, skill) => bytes + Buffer.byteLength(skill.instructions), 0)));
    for (const skill of autoSkills) {
      sessionStore.appendEvent(sessionId, "skill_auto_activated", JSON.stringify({ id: skill.id, name: skill.name, sourceSessionId: skill.sourceSessionId ?? null }));
    }
    sessionStore.appendEvent(sessionId, "user_input", redactRuntimeText(request.prompt));
    if (request.actor) sessionStore.appendEvent(sessionId, "actor_bound", request.actor);
    sessionStore.appendEvent(sessionId, "context_manifest", JSON.stringify(context.manifest));
    sessionStore.updateStatus(sessionId, "running");
    await emitHook("session.start", { sessionId, profile: profile.name, provider: profile.provider });
    const skillContent = [...skills, ...autoSkills].map((skill) => `## Skill: ${skill.name}\n${skill.instructions}`).join("\n\n");
    const profileContract = JSON.stringify({
      profile: profile.name, role: profile.role, provider: profile.provider, model: profile.model,
      clientBinding: profile.clients[profile.provider] ?? { enabled: true, capabilities: [], limitations: [] },
      allowedPaths: profile.allowedPaths, allowedCommands: profile.allowedCommands, writePolicy: profile.writePolicy,
      approvalRequired: profile.governance?.approvalRequired ?? false, verification: profile.verification.commands,
      memoryScope: profile.memory.enabled ? profile.memory.scope : "disabled", ticketId: effectiveTicketId,
      handoffId: request.handoffId ?? null,
      contextCompression: profile.contextCompression,
    });
    const handoffContent = typeof handoff?.compactContext === "string" ? `## Atlas handoff\n${handoff.compactContext}` : "";
    const prompt = [request.prompt, `## Effective Atlas profile\n${profileContract}`, profile.instructions, skillContent, formatProfileFacts(profileFacts), handoffContent, context.content].filter(Boolean).join("\n\n");
    const contextHash = createHash("sha256").update(prompt).digest("hex");
    sessionStore.updateContext(sessionId, contextHash, Buffer.byteLength(prompt));
    sessionStore.appendEvent(sessionId, "context_cost", JSON.stringify({ bytes: Buffer.byteLength(prompt), sources: context.manifest.files, handoffId: request.handoffId ?? null, selectedSkills: [...skills, ...autoSkills].map((skill) => skill.name) }));
    const result = await execute({
      provider: profile.provider as HeadlessProvider,
      prompt,
      cwd: request.cwd,
      clientHome,
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
    sessionStore.scanCaptureItems(sessionId);
    await appendRuntimeLog({ timestamp: new Date().toISOString(), event: result.exitCode === 124 ? "provider_timeout" : "run_finished", correlationId: sessionId, sessionId, provider: profile.provider, status: result.exitCode === 0 ? "completed" : "failed", payload: JSON.stringify({ exitCode: result.exitCode }) });
    await finalizeSession(sessionStore, sessionId, { exitCode: result.exitCode });
    await emitHook("session.end", { sessionId, status: result.exitCode === 0 ? "completed" : "failed", exitCode: result.exitCode });
    return sessionStore.get(sessionId) ?? session;
  } catch (error) {
    sessionStore.updateStatus(sessionId, "failed");
    sessionStore.scanCaptureItems(sessionId);
    sessionStore.appendEvent(sessionId, "error", error instanceof Error ? error.message : String(error));
    await finalizeSession(sessionStore, sessionId, { exitCode: 1 });
    await emitHook("run.error", { sessionId, error: error instanceof Error ? error.message : String(error) });
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
    sessionStore.appendEvent(sessionId, "user_input", redactRuntimeText(prompt));
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
    sessionStore.scanCaptureItems(sessionId);
    await finalizeSession(sessionStore, sessionId, { exitCode: result.exitCode });
    return sessionStore.get(sessionId) ?? existing;
  } catch (error) {
    sessionStore.updateStatus(sessionId, "failed");
    sessionStore.scanCaptureItems(sessionId);
    sessionStore.appendEvent(sessionId, "error", error instanceof Error ? error.message : String(error));
    await finalizeSession(sessionStore, sessionId, { exitCode: 1 });
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
    if (typeof providerSessionId === "string" && isValidProviderSessionId(providerSessionId)) store.updateProviderSessionId(sessionId, providerSessionId);
  }
}

export function isValidProviderSessionId(value: string): boolean {
  return value.length <= 256 && /^[A-Za-z0-9._:-]+$/.test(value);
}
