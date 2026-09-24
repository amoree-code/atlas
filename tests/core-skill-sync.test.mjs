import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  coreSkillReports,
  syncCoreSkills,
} from "../dist/application/skills/core-skill-sync.js";

test("core skill sync copies canonical skills and preserves non-core skills", async () => {
  const home = await mkdtemp(path.join(os.tmpdir(), "atlas-skills-"));
  try {
    await mkdir(path.join(home, ".claude", "skills", "custom"), { recursive: true });
    await writeFile(path.join(home, ".claude", "skills", "custom", "SKILL.md"), "custom");
    await mkdir(path.join(home, ".codex", "skills"), { recursive: true });

    const synced = await syncCoreSkills(home);
    assert.equal(synced.find((item) => item.client === "claude")?.status, "synchronized");
    assert.equal(synced.find((item) => item.client === "codex")?.status, "synchronized");
    assert.equal(await readFile(path.join(home, ".claude", "skills", "custom", "SKILL.md"), "utf8"), "custom");

    const reports = await coreSkillReports(home);
    assert.equal(reports.find((item) => item.client === "claude")?.status, "synchronized");
    await writeFile(path.join(home, ".claude", "skills", "catch-up", "SKILL.md"), "drift");
    assert.equal(reports.find((item) => item.client === "codex")?.status, "synchronized");
    assert.equal((await coreSkillReports(home)).find((item) => item.client === "claude")?.status, "drifted");
  } finally {
    await rm(home, { recursive: true, force: true });
  }
});
