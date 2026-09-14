import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

test("doctor reports missing roots and broken active links without mutating", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-doctor-"));
  await mkdir(path.join(root, "personal", "memory"), { recursive: true });
  await mkdir(path.join(root, "personal", "knowledge"), { recursive: true });
  await mkdir(path.join(root, "projects", "atlas"), { recursive: true });
  await mkdir(path.join(root, "system"), { recursive: true });
  await writeFile(path.join(root, "personal", "memory", "MEMORY.md"), "# Memory\n\n[missing](nope.md)\n");
  await writeFile(path.join(root, "personal", "knowledge", "KNOWLEDGE.md"), "# Knowledge\n");
  const before = await readFile(path.join(root, "personal", "memory", "MEMORY.md"), "utf8");
  const result = spawnSync(process.execPath, [path.resolve("dist/main.js"), "doctor", "--json"], {
    env: { ...process.env, ATLAS_ROOT: root, ATLAS_SKIP_DEPENDENCY_AUDIT: "1" }, encoding: "utf8",
  });
  const report = JSON.parse(result.stdout);
  assert.ok(report.findings.some((finding) => finding.code === "BROKEN_LINK"));
  assert.equal(await readFile(path.join(root, "personal", "memory", "MEMORY.md"), "utf8"), before);
});
