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
