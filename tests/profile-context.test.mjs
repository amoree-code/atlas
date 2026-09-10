import assert from "node:assert/strict";
import { mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildContext } from "../dist/infrastructure/filesystem/context-manager.js";
import { validateContextManifest } from "../dist/domain/context/context-validator.js";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";

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

test("rejects a profile with an unknown write policy", () => {
  assert.throws(() => validateProfile({
    name: "bad", provider: "claude", model: "sonnet", role: "assistant", writePolicy: "unrestricted",
  }));
});

test("defaults skills, allowedPaths, allowedCommands, contextSources, and writePolicy", () => {
  const profile = validateProfile({ name: "minimal", provider: "claude", model: "sonnet", role: "assistant" });
  assert.deepEqual(profile.skills, []);
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
