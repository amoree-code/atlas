import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { SessionStore } from "../dist/infrastructure/persistence/session-store.js";
import { assertValidStatusTransition } from "../dist/domain/sessions/session.js";
import { validateSession } from "../dist/infrastructure/persistence/session-validator.js";

async function openStore() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "atlas-session-"));
  return new SessionStore(path.join(directory, "sessions.sqlite"));
}

test("stores a session and its events without extra application data", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "atlas-session-"));
  const store = new SessionStore(path.join(directory, "sessions.sqlite"));
  store.create({
    sessionId: "parent-1",
    provider: "claude",
    providerSessionId: null,
    parentSessionId: null,
    profile: "default",
    workingDirectory: directory,
    resumeData: null,
  });
  store.create({
    sessionId: "child-1",
    provider: "codex",
    providerSessionId: "codex-session",
    parentSessionId: "parent-1",
    profile: "reviewer",
    workingDirectory: directory,
    resumeData: null,
  });
  store.appendEvent("child-1", "completed", "review complete");

  assert.equal(store.get("child-1").parentSessionId, "parent-1");
  assert.deepEqual(store.listEvents("child-1").map((event) => event.type), ["completed"]);
  store.close();
});

test("allows the full valid lifecycle, including resuming a completed session", async () => {
  const store = await openStore();
  store.create({
    sessionId: "s1", provider: "claude", providerSessionId: null, parentSessionId: null,
    profile: "default", workingDirectory: "/tmp", resumeData: null,
  });
  assert.equal(store.get("s1").status, "created");

  store.updateStatus("s1", "running");
  store.updateStatus("s1", "completed");
  assert.equal(store.get("s1").status, "completed");

  // Resuming re-enters "running" from a completed run.
  store.updateStatus("s1", "running");
  store.updateStatus("s1", "failed");
  assert.equal(store.get("s1").status, "failed");

  // Retrying re-enters "running" from a failed run, and can end in cancelled.
  store.updateStatus("s1", "running");
  store.updateStatus("s1", "cancelled");
  assert.equal(store.get("s1").status, "cancelled");

  store.close();
});

test("rejects transitions that skip or leave the lifecycle contract", async () => {
  const store = await openStore();
  store.create({
    sessionId: "s2", provider: "claude", providerSessionId: null, parentSessionId: null,
    profile: "default", workingDirectory: "/tmp", resumeData: null,
  });

  assert.throws(() => store.updateStatus("s2", "completed"), /Invalid session status transition: created -> completed/);
  assert.throws(() => store.updateStatus("s2", "cancelled"), /Invalid session status transition: created -> cancelled/);

  store.updateStatus("s2", "running");
  store.updateStatus("s2", "cancelled");
  assert.throws(() => store.updateStatus("s2", "running"), /Invalid session status transition: cancelled -> running/);

  store.close();
});

test("updateStatus rejects an unknown session id", async () => {
  const store = await openStore();
  assert.throws(() => store.updateStatus("missing", "running"), /Session not found: missing/);
  store.close();
});

test("assertValidStatusTransition treats a same-status update as a no-op", () => {
  assert.doesNotThrow(() => assertValidStatusTransition("running", "running"));
  assert.doesNotThrow(() => assertValidStatusTransition("cancelled", "cancelled"));
});

test("validateSession rejects a malformed session record", () => {
  assert.throws(() => validateSession({
    sessionId: "s3", provider: "claude", providerSessionId: null, parentSessionId: null,
    profile: "default", workingDirectory: "/tmp", status: "not-a-real-status",
    createdAt: "now", updatedAt: "now", resumeData: null,
  }));
  assert.throws(() => validateSession({
    sessionId: "", provider: "claude", providerSessionId: null, parentSessionId: null,
    profile: "default", workingDirectory: "/tmp", status: "created",
    createdAt: "now", updatedAt: "now", resumeData: null,
  }));
});
