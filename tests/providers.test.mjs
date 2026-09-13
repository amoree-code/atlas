import assert from "node:assert/strict";
import { chmod, mkdtemp, mkdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildProviderInvocation, providerAdapterRegistry, runProvider } from "../dist/infrastructure/providers/providers.js";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";
import { resolveClientHome } from "../dist/infrastructure/providers/client-home.js";

test("builds the Claude CLI stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "claude", prompt: "hello", cwd: "/tmp",
  }), {
    command: "claude",
    args: ["-p", "hello", "--verbose", "--output-format", "stream-json"],
  });
});

test("exposes one adapter with capabilities for every registered headless provider", () => {
  assert.deepEqual(Object.keys(providerAdapterRegistry).sort(), ["antigravity", "claude", "codex", "gemini", "hermes"]);
  assert.ok(providerAdapterRegistry.claude.capabilities.includes("resume"));
});

test("builds the Codex JSON contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "codex", prompt: "hello", cwd: "/tmp",
  }), {
    command: "codex",
    args: ["exec", "--json", "hello"],
  });
});

test("builds the Gemini stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "gemini", prompt: "hello", cwd: "/tmp",
  }), {
    command: "gemini",
    args: ["--prompt", "hello", "--output-format", "stream-json"],
  });
});

test("builds the Hermes one-shot contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "hermes", prompt: "hello", cwd: "/tmp",
  }), {
    command: "hermes",
    args: ["-z", "hello"],
  });
});

test("accepts Gemini as a profile provider", () => {
  assert.equal(validateProfile({
    name: "gemini", provider: "gemini", model: "flash", role: "assistant",
  }).provider, "gemini");
});

test("adds Claude resume ids without changing the CLI stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "claude", prompt: "continue", cwd: "/tmp", resumeId: "session-1",
  }).args, ["--resume", "session-1", "-p", "continue", "--verbose", "--output-format", "stream-json"]);
});

test("headless providers bypass Atlas shims and run the original executable", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-headless-provider-"));
  const shim = path.join(root, "shims");
  const staleShim = path.join(root, "old", "runtime", "shims");
  const bin = path.join(root, "bin");
  await mkdir(shim);
  await mkdir(staleShim, { recursive: true });
  await mkdir(bin);
  await writeFile(path.join(shim, "codex"), "#!/bin/sh\nexit 99\n");
  await chmod(path.join(shim, "codex"), 0o755);
  await writeFile(path.join(staleShim, "codex"), "#!/bin/sh\nexit 98\n");
  await chmod(path.join(staleShim, "codex"), 0o755);
  const original = path.join(bin, "codex");
  await writeFile(original, "#!/bin/sh\nprintf '{\"session_id\":\"codex-test\"}\\n'\n");
  await chmod(original, 0o755);

  const previousRoot = process.env.ATLAS_ROOT;
  const previousShim = process.env.ATLAS_SHIM_DIR;
  const previousPath = process.env.PATH;
  process.env.ATLAS_ROOT = root;
  process.env.ATLAS_SHIM_DIR = shim;
  process.env.PATH = `${shim}${path.delimiter}${staleShim}${path.delimiter}${bin}`;
  try {
    const result = await runProvider({ provider: "codex", prompt: "hello", cwd: root });
    assert.equal(result.exitCode, 0);
    assert.deepEqual(result.events[0], { type: "json", data: { session_id: "codex-test" } });
  } finally {
    if (previousRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previousRoot;
    if (previousShim === undefined) delete process.env.ATLAS_SHIM_DIR; else process.env.ATLAS_SHIM_DIR = previousShim;
    if (previousPath === undefined) delete process.env.PATH; else process.env.PATH = previousPath;
  }
});

test("resolves a configured client home only inside Atlas system/clients", () => {
  const previousRoot = process.env.ATLAS_ROOT;
  const root = "/tmp/atlas-client-home-test";
  process.env.ATLAS_ROOT = root;
  try {
    const profile = validateProfile({
      name: "developer", role: "developer", clients: {
        hermes: { enabled: true, home: "system/clients/hermes/developer" },
      },
    });
    assert.equal(resolveClientHome(profile), path.join(root, "system/clients/hermes/developer"));
    const unsafe = validateProfile({ name: "bad", role: "assistant", clients: { hermes: { enabled: true, home: "../secrets" } } });
    assert.throws(() => resolveClientHome(unsafe), /must stay under Atlas system\/clients/);
  } finally {
    if (previousRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previousRoot;
  }
});
