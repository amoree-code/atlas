import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { loadProfile } from "../dist/infrastructure/filesystem/profile-loader.js";
import { openSessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("loadProfile reads profiles from private ATLAS_ROOT/profiles, not the engine tree", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-profile-loader-"));
  await mkdir(path.join(root, "profiles"), { recursive: true });
  await writeFile(path.join(root, "profiles", "reviewer.json"), JSON.stringify({
    name: "reviewer", provider: "claude", model: "sonnet", role: "review only",
  }));

  process.env.ATLAS_ROOT = root;
  try {
    const profile = await loadProfile("reviewer");
    assert.equal(profile.name, "reviewer");
    assert.equal(profile.provider, "claude");
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("loadProfile rejects a name whose file does not exist under ATLAS_ROOT", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-profile-loader-missing-"));
  process.env.ATLAS_ROOT = root;
  try {
    await assert.rejects(loadProfile("missing"));
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("openSessionStore persists sessions under ATLAS_ROOT/sessions/sessions.sqlite", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-session-persist-"));
  process.env.ATLAS_ROOT = root;
  try {
    const store = await openSessionStore();
    store.create({
      sessionId: "persisted-1", provider: "claude", providerSessionId: null, parentSessionId: null,
      profile: "default", workingDirectory: root, resumeData: null,
    });
    store.close();

    const reopened = await openSessionStore();
    assert.equal(reopened.get("persisted-1").sessionId, "persisted-1");
    reopened.close();
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});
