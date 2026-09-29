import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PERSONAL_DIR, PROJECTS_DIR, SYSTEM_DIR } from "../dist/paths.js";

test("doctor reports missing roots and broken active links without mutating", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-doctor-"));
  await mkdir(path.join(root, PERSONAL_DIR, "memory"), { recursive: true });
  await mkdir(path.join(root, PERSONAL_DIR, "knowledge"), { recursive: true });
  await mkdir(path.join(root, PROJECTS_DIR, "atlas"), { recursive: true });
  await mkdir(path.join(root, SYSTEM_DIR), { recursive: true });
  await writeFile(
    path.join(root, PERSONAL_DIR, "memory", "MEMORY.md"),
    "# Memory\n\n[missing](nope.md)\n",
  );
  await writeFile(
    path.join(root, PERSONAL_DIR, "knowledge", "KNOWLEDGE.md"),
    "# Knowledge\n",
  );
  const before = await readFile(
    path.join(root, PERSONAL_DIR, "memory", "MEMORY.md"),
    "utf8",
  );
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "doctor", "--json"],
    {
      env: {
        ...process.env,
        ATLAS_ROOT: root,
        ATLAS_SKIP_DEPENDENCY_AUDIT: "1",
      },
      encoding: "utf8",
    },
  );
  const report = JSON.parse(result.stdout);
  assert.ok(report.findings.some((finding) => finding.code === "BROKEN_LINK"));
  assert.equal(
    await readFile(
      path.join(root, PERSONAL_DIR, "memory", "MEMORY.md"),
      "utf8",
    ),
    before,
  );
});
