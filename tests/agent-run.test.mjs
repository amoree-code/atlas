import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { runAgent, resumeAgent } from "../dist/application/runs/run-agent.js";
import { SessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("connects profile, context, headless execution, and session storage", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-agent-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "reviewer.json"), JSON.stringify({
    name: "reviewer", provider: "claude", model: "sonnet", role: "review only", skills: ["verification"],
    allowedPaths: ["README.md"], contextSources: ["README.md"],
  }));
  await writeFile(path.join(root, "README.md"), "project context");
  const database = path.join(root, "sessions", "sessions.sqlite");
  process.env.ATLAS_ROOT = root;
  const session = await runAgent({ profileName: "reviewer", prompt: "Review", cwd: root }, async (request) => {
    assert.equal(request.provider, "claude");
    assert.match(request.prompt, /project context/);
    assert.match(request.prompt, /Skill: verification/);
    request.onEvent?.({ type: "json", data: { text: "done" } });
    return { exitCode: 0, events: [], stderr: "" };
  });

  const store = new SessionStore(database);
  assert.equal(session.status, "completed");
  assert.deepEqual(store.listEvents(session.sessionId).map((event) => event.type), ["context_manifest", "json", "process_exit", "evidence"]);
  store.close();
  delete process.env.ATLAS_ROOT;
});

test("transitions status from created to running to completed, visible to a concurrent reader", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-status-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "default.json"), JSON.stringify({
    name: "default", provider: "claude", model: "sonnet", role: "assistant",
  }));
  const database = path.join(root, "sessions", "sessions.sqlite");
  process.env.ATLAS_ROOT = root;
  const sessionId = "status-check-session";
  const session = await runAgent({ profileName: "default", prompt: "start", cwd: root, sessionId }, async () => {
    const reader = new SessionStore(database);
    const current = reader.get(sessionId);
    assert.equal(current.status, "running");
    reader.close();
    return { exitCode: 0, events: [], stderr: "" };
  });
  assert.equal(session.status, "completed");
  delete process.env.ATLAS_ROOT;
});

test("resumes a Claude session using its provider session id", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resume-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "default.json"), JSON.stringify({
    name: "default", provider: "claude", model: "sonnet", role: "assistant",
  }));
  process.env.ATLAS_ROOT = root;
  const first = await runAgent({ profileName: "default", prompt: "start", cwd: root }, async (request) => {
    request.onEvent?.({ type: "json", data: { session_id: "provider-1" } });
    return { exitCode: 0, events: [], stderr: "" };
  });
  const resumed = await resumeAgent(first.sessionId, "continue", async (request) => {
    assert.equal(request.resumeId, "provider-1");
    return { exitCode: 0, events: [], stderr: "" };
  });
  assert.equal(resumed.status, "completed");
  delete process.env.ATLAS_ROOT;
});

test("marks the session failed and records the error event when the provider throws", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-fail-throw-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "default.json"), JSON.stringify({
    name: "default", provider: "claude", model: "sonnet", role: "assistant",
  }));
  const database = path.join(root, "sessions", "sessions.sqlite");
  process.env.ATLAS_ROOT = root;

  await assert.rejects(
    runAgent({ profileName: "default", prompt: "start", cwd: root }, async () => {
      throw new Error("provider crashed");
    }),
    /provider crashed/,
  );

  const store = new SessionStore(database);
  const [session] = store.list();
  assert.equal(session.status, "failed");
  assert.deepEqual(store.listEvents(session.sessionId).map((event) => event.type), ["context_manifest", "error"]);
  store.close();
  delete process.env.ATLAS_ROOT;
});

test("marks the session failed when the provider exits non-zero without throwing", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-fail-exit-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "default.json"), JSON.stringify({
    name: "default", provider: "claude", model: "sonnet", role: "assistant",
  }));
  const database = path.join(root, "sessions", "sessions.sqlite");
  process.env.ATLAS_ROOT = root;

  const session = await runAgent({ profileName: "default", prompt: "start", cwd: root }, async () => {
    return { exitCode: 1, events: [], stderr: "boom" };
  });

  assert.equal(session.status, "failed");
  const store = new SessionStore(database);
  const exitEvent = store.listEvents(session.sessionId).find((event) => event.type === "process_exit");
  assert.deepEqual(JSON.parse(exitEvent.data), { exitCode: 1, stderr: "boom" });
  store.close();
  delete process.env.ATLAS_ROOT;
});

test("closes its session store exactly once, on both the success and failure paths", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-shutdown-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "default.json"), JSON.stringify({
    name: "default", provider: "claude", model: "sonnet", role: "assistant",
  }));
  process.env.ATLAS_ROOT = root;

  const originalClose = SessionStore.prototype.close;
  let closeCalls = 0;
  SessionStore.prototype.close = function patchedClose(...args) {
    closeCalls += 1;
    return originalClose.apply(this, args);
  };

  try {
    await runAgent({ profileName: "default", prompt: "start", cwd: root }, async () => {
      return { exitCode: 0, events: [], stderr: "" };
    });
    assert.equal(closeCalls, 1);

    await assert.rejects(
      runAgent({ profileName: "default", prompt: "start", cwd: root }, async () => {
        throw new Error("provider crashed");
      }),
    );
    assert.equal(closeCalls, 2);
  } finally {
    SessionStore.prototype.close = originalClose;
    delete process.env.ATLAS_ROOT;
  }
});
