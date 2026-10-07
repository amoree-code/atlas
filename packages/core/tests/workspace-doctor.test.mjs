import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  KNOWLEDGE_DIR,
  PERSONAL_DIR,
  PROJECTS_DIR,
  SYSTEM_DIR,
} from "../dist/paths.js";

test("doctor reports missing roots and broken active links without mutating", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-doctor-"));
  await mkdir(path.join(root, PERSONAL_DIR), { recursive: true });
  await mkdir(path.join(root, KNOWLEDGE_DIR), { recursive: true });
  await mkdir(path.join(root, PROJECTS_DIR, "atlas"), { recursive: true });
  await mkdir(path.join(root, SYSTEM_DIR), { recursive: true });
  await writeFile(
    path.join(root, PERSONAL_DIR, "MEMORY.md"),
    "# Memory\n\n[missing](nope.md)\n",
  );
  await writeFile(
    path.join(root, KNOWLEDGE_DIR, "KNOWLEDGE.md"),
    "# Knowledge\n",
  );
  const before = await readFile(
    path.join(root, PERSONAL_DIR, "MEMORY.md"),
    "utf8",
  );
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "doctor", "--json"],
    {
      env: {
        ...process.env,
        OCEAN_ROOT: root,
        OCEAN_SKIP_DEPENDENCY_AUDIT: "1",
      },
      encoding: "utf8",
    },
  );
  const report = JSON.parse(result.stdout);
  assert.ok(report.findings.some((finding) => finding.code === "BROKEN_LINK"));
  assert.equal(
    await readFile(path.join(root, PERSONAL_DIR, "MEMORY.md"), "utf8"),
    before,
  );
});

test("policy doctor reads policy references written as `ocean policy` or the legacy `atlas policy`", async () => {
  const { CHARTER_DIR, POLICIES_DIR } = await import("../dist/paths.js");
  const root = await mkdtemp(path.join(os.tmpdir(), "ocean-policy-doctor-"));
  await mkdir(path.join(root, POLICIES_DIR), { recursive: true });
  await writeFile(path.join(root, POLICIES_DIR, "task.md"), "# task\n");
  await writeFile(
    path.join(root, CHARTER_DIR, "core.md"),
    [
      "Load `ocean policy task` when starting work.",
      "Load `atlas policy task` too (legacy wording).",
      "Load `ocean policy list` to see them all.",
      "Load `ocean policy missing-one` and `atlas policy missing-two`.",
    ].join("\n"),
  );
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "policy", "doctor"],
    { encoding: "utf8", env: { ...process.env, OCEAN_ROOT: root } },
  );
  const report = JSON.parse(result.stdout);
  assert.deepEqual(report.missing.sort(), ["missing-one", "missing-two"]);
  assert.equal(report.ok, false);
});

test("doctor GOVERNANCE_DRIFT reads policy references written as `ocean policy` or the legacy `atlas policy`", async () => {
  const { CHARTER_DIR, POLICIES_DIR } = await import("../dist/paths.js");
  const root = await mkdtemp(path.join(os.tmpdir(), "ocean-doctor-drift-"));
  await mkdir(path.join(root, POLICIES_DIR), { recursive: true });
  await writeFile(path.join(root, POLICIES_DIR, "task.md"), "# task\n");
  const run = async (core) => {
    await writeFile(path.join(root, CHARTER_DIR, "core.md"), core);
    const result = spawnSync(
      process.execPath,
      [path.resolve("dist/main.js"), "doctor", "--json"],
      {
        env: {
          ...process.env,
          OCEAN_ROOT: root,
          OCEAN_SKIP_DEPENDENCY_AUDIT: "1",
        },
        encoding: "utf8",
      },
    );
    return JSON.parse(result.stdout).findings.filter(
      (finding) => finding.code === "GOVERNANCE_DRIFT",
    );
  };
  assert.equal(
    (await run("Use `ocean policy task` and `atlas policy task`.\n")).length,
    0,
  );
  const drift = await run("Use `ocean policy gone` first.\n");
  assert.equal(drift.length, 1);
  assert.match(drift[0].message, /gone/);
  assert.equal((await run("Use `atlas policy gone-too` first.\n")).length, 1);
});
