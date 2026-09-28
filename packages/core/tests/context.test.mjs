import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";
import { buildContext } from "../dist/infrastructure/filesystem/context-manager.js";

test("context returns a compact JSON packet without loading task bodies", () => {
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "context", "--json"],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  const packet = JSON.parse(result.stdout);
  assert.equal(packet.project, "atlas");
  assert.equal(packet.version, "0.3.6");
  assert.deepEqual(packet.roots, ["personal", "projects", "system"]);
  assert.ok(Array.isArray(packet.tasks));
});

test("context rejects symlinks that escape allowed paths", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-context-link-"));
  const outside = await mkdtemp(
    path.join(os.tmpdir(), "atlas-context-outside-"),
  );
  await mkdir(path.join(root, "allowed"));
  await writeFile(path.join(outside, "secret.md"), "outside secret");
  await symlink(
    path.join(outside, "secret.md"),
    path.join(root, "allowed", "linked.md"),
  );
  const profile = validateProfile({
    name: "reader",
    provider: "claude",
    role: "reader",
    allowedPaths: ["allowed"],
    contextSources: ["allowed/linked.md"],
  });
  const context = await buildContext(profile, root);
  assert.equal(context.content, "");
  assert.deepEqual(context.manifest.omitted, ["allowed/linked.md"]);
});

test("context enforces byte budgets for multibyte text", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-context-bytes-"));
  await writeFile(path.join(root, "arabic.md"), "مرحبا".repeat(100));
  const profile = validateProfile({
    name: "reader",
    provider: "claude",
    role: "reader",
    allowedPaths: ["arabic.md"],
    contextSources: ["arabic.md"],
  });
  const context = await buildContext(profile, root, 11);
  assert.ok(context.manifest.bytes <= 11);
  assert.ok(
    Buffer.byteLength(context.content.split("\n").slice(1).join("\n")) <= 11,
  );
  assert.ok(!context.content.includes("�"));
});
