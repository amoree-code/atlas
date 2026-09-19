import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { finalizeSession } from "../dist/application/memory/session-closeout.js";
import { SessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("finalizes a session with a bounded human summary, metadata, and handoff", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-session-closeout-"));
  process.env.ATLAS_ROOT = root;
  await mkdir(path.join(root, "system", "sessions"), { recursive: true });
  const store = new SessionStore(
    path.join(root, "system", "sessions", "sessions.sqlite"),
  );
  const sessionId = "closeout-session-1";
  store.create({
    sessionId,
    title: "Closeout test",
    ticketId: null,
    handoffId: null,
    provider: "claude",
    providerSessionId: null,
    parentSessionId: null,
    profile: "reviewer",
    profileIdentity: "profile-hash",
    workingDirectory: root,
    resumeData: null,
  });
  store.updateStatus(sessionId, "running");
  store.appendEvent(
    sessionId,
    "user_input",
    "Review the session closeout behavior",
  );
  const providerSecret = ["sk", "-ant-closeout-secret"].join("");
  store.appendEvent(
    sessionId,
    "provider_output",
    `Inspected the session flow and found one bounded result. ${providerSecret}`,
  );
  store.appendEvent(sessionId, "process_exit", JSON.stringify({ exitCode: 0 }));
  store.appendEvent(
    sessionId,
    "evidence",
    JSON.stringify({
      result: "proven",
      criterion: "provider process exits successfully",
    }),
  );
  store.updateStatus(sessionId, "completed");

  const result = await finalizeSession(store, sessionId, { exitCode: 0 });
  const summary = await readFile(path.join(root, result.summaryPath), "utf8");
  const saved = store.get(sessionId);

  const today = new Date().toISOString().slice(0, 10);
  const daily = await readFile(
    path.join(root, "personal", "daily", `${today}.md`),
    "utf8",
  );
  assert.match(daily, /^# Daily/);
  assert.match(daily, /## Work log/);
  assert.match(daily, /Review the session closeout behavior/);
  assert.doesNotMatch(daily, new RegExp(providerSecret));

  assert.match(summary, /# Session Summary/);
  assert.match(summary, /Review the session closeout behavior/);
  assert.match(summary, /Inspected the session flow/);
  assert.doesNotMatch(summary, new RegExp(providerSecret));
  assert.match(summary, /## Next action/);
  assert.equal(saved.summaryPath, result.summaryPath);
  assert.equal(saved.summaryHash, result.summaryHash);
  assert.ok(saved.summaryBytes > 0);
  assert.equal(saved.closeoutStatus, "completed");
  assert.ok(saved.handoffId);
  assert.equal(store.getHandoff(saved.handoffId).sourceSessionId, sessionId);
  assert.ok(
    store
      .listEvents(sessionId)
      .some((event) => event.type === "session_summary"),
  );
  const second = await finalizeSession(store, sessionId, { exitCode: 0 });
  assert.equal(second.summaryPath, result.summaryPath);
  assert.equal(
    store
      .listEvents(sessionId)
      .filter((event) => event.type === "session_summary").length,
    1,
  );
  assert.equal(store.listHandoffs().length, 1);
  store.close();
  delete process.env.ATLAS_ROOT;
});
