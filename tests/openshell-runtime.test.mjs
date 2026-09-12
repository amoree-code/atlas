import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { buildOpenShellInvocation, writeOpenShellPolicy } from "../dist/infrastructure/sandbox/openshell-runtime.js";

test("builds a fail-closed OpenShell invocation", () => {
  const invocation = buildOpenShellInvocation({ command: "claude", args: ["-p", "hello"], cwd: "/workspace" }, "/tmp/policy.yaml");
  assert.equal(invocation.command, "openshell");
  assert.deepEqual(invocation.args, ["sandbox", "create", "--no-keep", "--no-auto-providers", "--policy", "/tmp/policy.yaml", "--", "claude", "-p", "hello"]);
});

test("enables OpenShell local provider bootstrap only by explicit Atlas opt-in", () => {
  const invocation = buildOpenShellInvocation({ command: "codex", args: [], cwd: "/workspace", environment: { ATLAS_OPENSHELL_AUTO_PROVIDERS: "1" } }, "/tmp/policy.yaml");
  assert.ok(invocation.args.includes("--auto-providers"));
});

test("attaches only an explicitly selected OpenShell provider", () => {
  const invocation = buildOpenShellInvocation({ command: "codex", args: [], cwd: "/workspace", environment: { ATLAS_OPENSHELL_PROVIDER: "codex" } }, "/tmp/policy.yaml");
  assert.deepEqual(invocation.args.slice(4, 7), ["--provider", "codex", "--policy"]);
});

test("writes a bounded OpenShell filesystem policy", async () => {
  const root = await import("node:fs/promises").then(({ mkdtemp }) => mkdtemp(path.join(os.tmpdir(), "atlas-openshell-")));
  const oldRoot = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const result = await writeOpenShellPolicy({ command: "claude", args: [], cwd: "/workspace" });
    const policy = await readFile(result.policyPath, "utf8");
    assert.match(policy, /include_workdir: true/);
    assert.match(policy, /compatibility: best_effort/);
  } finally {
    if (oldRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = oldRoot;
  }
});

test("adds Codex network policy without widening other providers", async () => {
  const root = await import("node:fs/promises").then(({ mkdtemp }) => mkdtemp(path.join(os.tmpdir(), "atlas-openshell-")));
  const oldRoot = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const codex = await writeOpenShellPolicy({ command: "codex", args: [], cwd: "/workspace" });
    const codexPolicy = await readFile(codex.policyPath, "utf8");
    assert.match(codexPolicy, /host: chatgpt\.com/);
    assert.match(codexPolicy, /path: \/usr\/bin\/codex/);

    const unknown = await writeOpenShellPolicy({ command: "unknown-ai", args: [], cwd: "/workspace" });
    const unknownPolicy = await readFile(unknown.policyPath, "utf8");
    assert.doesNotMatch(unknownPolicy, /network_policies:/);
  } finally {
    if (oldRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = oldRoot;
  }
});
