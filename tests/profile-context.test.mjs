import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildContext } from "../dist/infrastructure/filesystem/context-manager.js";
import { validateContextManifest } from "../dist/domain/context/context-validator.js";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";
import { executionPolicy } from "../dist/domain/profiles/profile-policy.js";
import { selectProfileClient } from "../dist/domain/profiles/profile.js";

test("validates a profile and bounds context to allowed files", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-context-"));
  await writeFile(path.join(root, "allowed.md"), "allowed context");
  await writeFile(path.join(root, "private.md"), "private context");
  const profile = validateProfile({
    name: "reviewer",
    provider: "claude",
    model: "sonnet",
    role: "review only",
    allowedPaths: ["allowed.md"],
    contextSources: ["allowed.md", "private.md"],
  });
  const result = await buildContext(profile, root, 100);
  assert.deepEqual(result.manifest.files, ["allowed.md"]);
  assert.match(result.content, /allowed context/);
  assert.doesNotMatch(result.content, /private context/);
});

test("rejects a profile missing required fields", () => {
  assert.throws(() => validateProfile({ provider: "claude", model: "sonnet", role: "assistant" }));
});

test("rejects a profile with an unknown provider", () => {
  assert.throws(() => validateProfile({
    name: "bad", provider: "chatgpt", model: "sonnet", role: "assistant",
  }));
});

test("accepts Hermes as a profile provider", () => {
  assert.equal(validateProfile({
    name: "hermes", provider: "hermes", model: "provider-managed", role: "assistant",
  }).provider, "hermes");
});

test("rejects a profile with an unknown write policy", () => {
  assert.throws(() => validateProfile({
    name: "bad", provider: "claude", model: "sonnet", role: "assistant", writePolicy: "unrestricted",
  }));
});

test("defaults skills, allowedPaths, allowedCommands, contextSources, and writePolicy", () => {
  const profile = validateProfile({ name: "minimal", provider: "claude", model: "sonnet", role: "assistant" });
  assert.deepEqual(profile.skills, ["core-thinking", "verification"]);
  assert.deepEqual(profile.allowedPaths, []);
  assert.deepEqual(profile.allowedCommands, []);
  assert.deepEqual(profile.contextSources, []);
  assert.equal(profile.writePolicy, "none");
});

test("skips context sources outside every allowed path", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-context-"));
  await writeFile(path.join(root, "secret.md"), "top secret");
  const profile = validateProfile({
    name: "reviewer",
    provider: "claude",
    model: "sonnet",
    role: "review only",
    allowedPaths: [],
    contextSources: ["secret.md"],
  });
  const result = await buildContext(profile, root, 100);
  assert.deepEqual(result.manifest.files, []);
  assert.equal(result.content, "");
});

test("validates a well-formed context manifest", () => {
  const manifest = validateContextManifest({
    files: ["allowed.md"],
    bytes: 16,
    compactedSummary: null,
    lastContextCheckpoint: new Date().toISOString(),
  });
  assert.equal(manifest.bytes, 16);
});

test("accepts multiple enabled clients in one universal profile", () => {
  const profile = validateProfile({
    name: "developer",
    role: "developer",
    clients: {
      hermes: { enabled: true, profile: "developer" },
      codex: { enabled: true, model: "gpt-5" },
    },
  });
  assert.equal(profile.provider, "hermes");
  assert.equal(profile.clients.codex.model, "gpt-5");
});

test("rejects an unknown universal-profile client", () => {
  assert.throws(() => validateProfile({
    name: "bad", role: "assistant", clients: { unknown: { enabled: true } },
  }), /Unsupported client/);
});

test("selects an enabled client and rejects a disabled client", () => {
  const profile = validateProfile({
    name: "developer", role: "developer", clients: {
      hermes: { enabled: true, model: "provider-managed" },
      codex: { enabled: false, model: "gpt-5" },
    },
  });
  assert.equal(selectProfileClient(profile, "hermes").provider, "hermes");
  assert.throws(() => selectProfileClient(profile, "codex"), /not enabled/);
});

test("rejects a context manifest with negative bytes", () => {
  assert.throws(() => validateContextManifest({
    files: [],
    bytes: -1,
    compactedSummary: null,
    lastContextCheckpoint: new Date().toISOString(),
  }));
});

test("rejects a context manifest with an empty checkpoint", () => {
  assert.throws(() => validateContextManifest({
    files: [],
    bytes: 0,
    compactedSummary: null,
    lastContextCheckpoint: "",
  }));
});

test("rejects a context manifest missing required fields", () => {
  assert.throws(() => validateContextManifest({ files: [], bytes: 0 }));
});

test("enforces an explicit provider command allowlist", () => {
  const profile = validateProfile({ name: "reviewer", provider: "claude", model: "sonnet", role: "reviewer", allowedCommands: ["codex"] });
  assert.throws(() => executionPolicy(profile, "/tmp/project"), /Policy denied provider command/);
});

test("accepts an allowed provider and rejects empty allowed-paths policy", () => {
  const profile = validateProfile({ name: "developer", provider: "claude", model: "sonnet", role: "developer", allowedCommands: ["claude"], writePolicy: "workspace" });
  assert.equal(executionPolicy(profile, "/tmp/project").providerCommand, "claude");
  const restricted = validateProfile({ ...profile, writePolicy: "allowed-paths", allowedPaths: [] });
  assert.throws(() => executionPolicy(restricted, "/tmp/project"), /without allowed paths/);
});
