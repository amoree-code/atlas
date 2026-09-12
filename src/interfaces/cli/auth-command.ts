import { randomUUID } from "node:crypto";
import { authLogin, authStatus } from "../../application/auth/auth-orchestrator.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";

export async function runAuthCommand(action: string, provider: string): Promise<void> {
  if (!provider || !["status", "login"].includes(action)) {
    console.error("Usage: atlas auth status|login <client>");
    process.exitCode = 1;
    return;
  }
  const store = await openSessionStore();
  const sessionId = randomUUID();
  store.create({
    sessionId,
    provider,
    providerSessionId: null,
    parentSessionId: null,
    profile: `auth:${provider}`,
    profileIdentity: "",
    workingDirectory: process.cwd(),
    resumeData: null,
  });
  store.updateStatus(sessionId, "running");
  store.appendEvent(sessionId, "auth_started", JSON.stringify({ action, provider }));
  const state = action === "status" ? await authStatus(provider) : await authLogin(provider);
  store.appendEvent(sessionId, "auth_state", JSON.stringify({ state }));
  store.appendEvent(sessionId, "evidence", JSON.stringify({ type: "auth", result: state, criterion: "provider-owned authentication state" }));
  store.updateStatus(sessionId, ["failed", "cancelled", "not_supported"].includes(state) ? "failed" : "completed");
  store.close();
  console.log(JSON.stringify({ provider, state, sessionId }));
  if (state === "failed" || state === "not_supported") process.exitCode = 1;
}
