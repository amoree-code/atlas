import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { compressContext } from "../dist/application/context/context-compression.js";
import { listSkillCandidates } from "../dist/application/skills/skill-curation.js";
import {
  listObservations,
  observeSession,
  reviewObservation,
} from "../dist/application/skills/task-observer.js";
import { defaultSkillNames } from "../dist/domain/skills/default-skills.js";
import { buildContext } from "../dist/infrastructure/filesystem/context-manager.js";
import { openSessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("default skill policy stays small and verification-first", () => {
  assert.deepEqual(defaultSkillNames("general assistant"), [
    "core-thinking",
    "verification",
  ]);
  assert.deepEqual(defaultSkillNames("developer"), [
    "core-thinking",
    "verification",
  ]);
});

test("compression preserves required evidence and records recovery metadata", () => {
  const source = [
    "# Tool output",
    "changed files: src/app.ts",
    "verification: pnpm test passed",
    "security warning: never expose sensitive values",
    ...Array.from(
      { length: 80 },
      (_, index) => `repeated log line ${index % 4}`,
    ),
    "next action: inspect the remaining failure",
  ].join("\n");
  const result = compressContext({
    sourceId: "tool-1",
    content: source,
    budget: 260,
  });
  assert.equal(result.safeToUse, true);
  assert.equal(result.method, "atlas-bounded-v1");
  assert.ok(result.compressedBytes <= 260);
  assert.ok(result.originalBytes > result.compressedBytes);
  assert.match(result.content, /changed files/);
  assert.match(result.content, /verification/);
  assert.match(result.content, /next action/);
  assert.equal(result.recoveryRef, "tool-1");
});

test("compression falls back to bounded original when required evidence cannot fit safely", () => {
  const result = compressContext({
    sourceId: "tiny",
    content: "security warning: keep this",
    budget: 8,
  });
  assert.equal(result.safeToUse, false);
  assert.equal(result.method, "fallback-original-bounded");
  assert.equal(result.compressedBytes, Buffer.byteLength(result.content));
  assert.ok(result.compressedBytes <= 8);
});

test("profile-scoped compression keeps context within budget and records a benchmark", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-t194-context-"));
  const content = [
    'tool json: {"items":[1,2,3]}',
    "verification: passed",
    ...Array.from({ length: 100 }, () => "repeated log output"),
  ].join("\n");
  await mkdir(path.join(root, "context"), { recursive: true });
  await writeFile(path.join(root, "context", "output.txt"), content);
  const result = await buildContext(
    {
      name: "benchmark",
      description: "",
      version: "1",
      provider: "claude",
      model: "managed",
      role: "developer",
      skills: [],
      allowedPaths: ["context"],
      allowedCommands: [],
      writePolicy: "none",
      contextSources: ["context/output.txt"],
      clients: { claude: { enabled: true, capabilities: [], limitations: [] } },
      defaultClient: "claude",
      memory: { enabled: true, scope: "profile" },
      verification: { commands: [] },
      instructions: "",
      contextCompression: "atlas-bounded",
    },
    root,
    220,
    { compression: "atlas-bounded" },
  );
  assert.equal(result.manifest.compression.method, "atlas-bounded-v1");
  assert.ok(
    result.manifest.compression.originalBytes >
      result.manifest.compression.compressedBytes,
  );
  assert.ok(result.manifest.bytes <= 220);
  assert.match(result.content, /verification/);
  assert.equal(
    await readFile(
      path.join(root, result.manifest.compression.recoveryRef),
      "utf8",
    ),
    content,
  );
});

test("observer records proven repeated work without creating or promoting a skill", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-t194-observer-"));
  process.env.ATLAS_ROOT = root;
  const store = await openSessionStore();
  const sessionId = "observer-session";
  store.create({
    sessionId,
    provider: "codex",
    providerSessionId: null,
    parentSessionId: null,
    profile: "developer",
    profileIdentity: "profile-hash",
    workingDirectory: root,
    resumeData: null,
    taskId: "T-194",
  });
  store.updateStatus(sessionId, "running");
  store.appendEvent(
    sessionId,
    "provider_output",
    "Decision: use a bounded verification checklist.\nDecision: use a bounded verification checklist.",
  );
  store.appendEvent(
    sessionId,
    "evidence",
    JSON.stringify({ result: "proven", criterion: "tests pass" }),
  );
  store.updateStatus(sessionId, "completed");
  store.close();
  try {
    const observations = await observeSession(sessionId);
    assert.ok(observations.length >= 1);
    const observation = observations.find(
      (item) => item.signalType === "explicit-decision",
    );
    assert.ok(observation);
    assert.equal(observation.status, "observed");
    assert.equal(observation.sourceSessionId, sessionId);
    assert.equal(observation.taskId, "T-194");
    assert.ok(observation.evidenceRefs.length > 0);
    assert.deepEqual(await listObservations(), observations);
    assert.equal(
      (await reviewObservation(observations[0].observationId, "discarded"))
        .status,
      "discarded",
    );
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("observer only treats real user corrections as repeated-correction, not provider output mentioning those words", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-t194-observer-"));
  process.env.ATLAS_ROOT = root;
  const store = await openSessionStore();
  const sessionId = "observer-correction-session";
  store.create({
    sessionId,
    provider: "codex",
    providerSessionId: null,
    parentSessionId: null,
    profile: "developer",
    profileIdentity: "profile-hash",
    workingDirectory: root,
    resumeData: null,
    taskId: null,
  });
  store.updateStatus(sessionId, "running");
  store.appendEvent(
    sessionId,
    "provider_output",
    "--acp (Deprecated, use `kimi acp` instead) Run as ACP server.",
  );
  store.appendEvent(
    sessionId,
    "user_input",
    "no, use pnpm instead of npm for this repo",
  );
  store.appendEvent(
    sessionId,
    "evidence",
    JSON.stringify({ result: "proven", criterion: "tests pass" }),
  );
  store.updateStatus(sessionId, "completed");
  store.close();
  try {
    const observations = await observeSession(sessionId);
    const corrections = observations.filter(
      (item) => item.signalType === "repeated-correction",
    );
    assert.equal(corrections.length, 1);
    assert.match(corrections[0].summary, /use pnpm instead of npm/);
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("approving an observation creates a skill candidate, not just a status flag", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-t194-observer-"));
  process.env.ATLAS_ROOT = root;
  const store = await openSessionStore();
  const sessionId = "observer-approval-session";
  store.create({
    sessionId,
    provider: "codex",
    providerSessionId: null,
    parentSessionId: null,
    profile: "developer",
    profileIdentity: "profile-hash",
    workingDirectory: root,
    resumeData: null,
    taskId: null,
  });
  store.updateStatus(sessionId, "running");
  store.appendEvent(
    sessionId,
    "provider_output",
    "Decision: use a bounded verification checklist.\nDecision: use a bounded verification checklist.",
  );
  store.appendEvent(
    sessionId,
    "evidence",
    JSON.stringify({ result: "proven", criterion: "tests pass" }),
  );
  store.updateStatus(sessionId, "completed");
  store.close();
  try {
    const [observation] = await observeSession(sessionId);
    assert.equal(observation.skillCandidateId, null);
    const reviewed = await reviewObservation(
      observation.observationId,
      "approved",
    );
    assert.ok(reviewed.skillCandidateId);
    const candidates = await listSkillCandidates();
    const candidate = candidates.find(
      (item) => item.id === reviewed.skillCandidateId,
    );
    assert.ok(candidate);
    assert.equal(candidate.status, "candidate");
    assert.equal(candidate.sourceSessionId, sessionId);
    assert.equal(candidate.instructions, observation.summary);
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});
