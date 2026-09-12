import assert from "node:assert/strict";
import { chmod, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { applyProviderResourceAdapter, buildAtlasResourceInjection, resourceAdapterStatus } from "../dist/application/context/resource-injection.js";
import { intercept } from "../dist/interfaces/cli/intercept-command.js";
import { registerProvider } from "../dist/infrastructure/wrappers/wrapper-manager.js";
import { openSessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("Atlas selects allowlisted resources and bounds the injected context", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resources-"));
  const memory = path.join(root, "personal", "memory");
  await mkdir(memory, { recursive: true });
  await writeFile(path.join(memory, "MEMORY.md"), "atlas-owned-memory-marker");
  await writeFile(path.join(root, "secret.txt"), "must-not-enter-context");
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const result = await buildAtlasResourceInjection();
    assert.deepEqual(result.manifest.files, ["personal/memory/MEMORY.md"]);
    assert.match(result.content, /atlas-owned-memory-marker/);
    assert.doesNotMatch(result.content, /must-not-enter-context/);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previous;
  }
});

test("Hermes interception passes Atlas context and records its manifest", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-hermes-context-"));
  const bin = path.join(root, "bin");
  await mkdir(path.join(root, "personal", "memory"), { recursive: true });
  await mkdir(bin, { recursive: true });
  await writeFile(path.join(root, "personal", "memory", "MEMORY.md"), "atlas-context-proof");
  const executable = path.join(bin, "hermes");
  await writeFile(executable, "#!/bin/sh\nprintf '%s\\n' \"$HERMES_ENVIRONMENT_HINT\"\nexit 0\n");
  await chmod(executable, 0o755);
  const previousRoot = process.env.ATLAS_ROOT;
  const previousPath = process.env.PATH;
  process.env.ATLAS_ROOT = root;
  process.env.PATH = `${bin}${path.delimiter}${previousPath}`;
  try {
    await registerProvider("hermes", "hermes");
    assert.equal(await intercept("hermes", ["--version"]), 0);
    const store = await openSessionStore();
    const session = store.list()[0];
    const events = store.listEvents(session.sessionId);
    assert.ok(events.some((event) => event.type === "atlas_resource_manifest"));
    assert.match(events.map((event) => event.data).join("\n"), /atlas-context-proof/);
    store.close();
  } finally {
    if (previousRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previousRoot;
    if (previousPath === undefined) delete process.env.PATH; else process.env.PATH = previousPath;
  }
});

test("resource injection selects a provider adapter without pretending unsupported clients consumed content", () => {
  assert.deepEqual(resourceAdapterStatus("hermes"), { transport: "hermes-environment-hint", consumesContent: true });
  for (const provider of ["claude", "codex", "gemini", "kimi", "kilo"]) {
    assert.deepEqual(resourceAdapterStatus(provider), { transport: "manifest-only", consumesContent: false });
  }
});

test("Claude print mode receives Atlas context through its official append-system-prompt flag", async () => {
  const injection = await buildAtlasResourceInjection();
  const result = applyProviderResourceAdapter("claude", ["-p", "check this"], injection);
  assert.equal(result.transport, "claude-append-system-prompt");
  assert.equal(result.consumesContent, true);
  assert.equal(result.args[0], "-p");
  assert.equal(result.args[1], "check this");
  assert.equal(result.args.at(-2), "--append-system-prompt");
  assert.match(result.args.at(-1), /# Atlas Resource Context/);
});

test("Claude interactive mode stays unchanged until an interactive adapter is proven", async () => {
  const injection = await buildAtlasResourceInjection();
  const args = ["--continue"];
  const result = applyProviderResourceAdapter("claude", args, injection);
  assert.deepEqual(result.args, args);
  assert.equal(result.transport, "manifest-only");
  assert.equal(result.consumesContent, false);
});

test("Codex exec mode receives Atlas context in its official prompt position", async () => {
  const injection = await buildAtlasResourceInjection();
  const result = applyProviderResourceAdapter("codex", ["exec", "--json", "review this"], injection);
  assert.equal(result.transport, "codex-exec-prompt");
  assert.equal(result.consumesContent, true);
  assert.equal(result.args[0], "exec");
  assert.equal(result.args[1], "--json");
  assert.match(result.args[2], /^review this\n\n# Atlas Resource Context/);
});

test("Codex interactive mode stays unchanged until an interactive adapter is proven", async () => {
  const injection = await buildAtlasResourceInjection();
  const args = [];
  const result = applyProviderResourceAdapter("codex", args, injection);
  assert.deepEqual(result.args, args);
  assert.equal(result.transport, "manifest-only");
  assert.equal(result.consumesContent, false);
});

test("Kilo run mode receives Atlas context as an additional message", async () => {
  const injection = await buildAtlasResourceInjection();
  const result = applyProviderResourceAdapter("kilo", ["run", "review this", "--format", "json"], injection);
  assert.equal(result.transport, "kilo-run-message");
  assert.equal(result.consumesContent, true);
  assert.equal(result.args[0], "run");
  assert.match(result.args[1], /^# Atlas Resource Context/);
  assert.equal(result.args[2], "review this");
});

test("Kilo prompt mode receives Atlas context through its prompt option", async () => {
  const injection = await buildAtlasResourceInjection();
  const result = applyProviderResourceAdapter("kilo", ["--prompt", "review this"], injection);
  assert.equal(result.transport, "kilo-prompt-option");
  assert.equal(result.consumesContent, true);
  assert.match(result.args[1], /^review this\n\n# Atlas Resource Context/);
});

test("Kilo interactive mode stays unchanged until an interactive adapter is proven", async () => {
  const injection = await buildAtlasResourceInjection();
  const args = [];
  const result = applyProviderResourceAdapter("kilo", args, injection);
  assert.deepEqual(result.args, args);
  assert.equal(result.transport, "manifest-only");
  assert.equal(result.consumesContent, false);
});

test("Copilot prompt mode receives Atlas context through its prompt option", async () => {
  const injection = await buildAtlasResourceInjection();
  const result = applyProviderResourceAdapter("copilot", ["-p", "review this", "--model", "auto"], injection);
  assert.equal(result.transport, "copilot-prompt-option");
  assert.equal(result.consumesContent, true);
  assert.match(result.args[1], /^review this\n\n# Atlas Resource Context/);
  assert.equal(result.args[2], "--model");
});
