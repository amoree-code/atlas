import assert from "node:assert/strict";
import test from "node:test";
import { listSkills, loadSkill, loadSkills } from "../dist/infrastructure/filesystem/skill-loader.js";
import { mkdir, writeFile } from "node:fs/promises";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";

test("lists the public core skill catalog without loading full instructions", async () => {
  const skills = await listSkills();
  assert.deepEqual(skills.map((skill) => skill.name), ["core-thinking", "verification", "catch-up", "session-handoff"]);
  assert.equal(Object.hasOwn(skills[0], "instructions"), false);
});

test("loads and validates a core skill on demand", async () => {
  const skill = await loadSkill("core-thinking");
  assert.equal(skill.category, "core");
  assert.match(skill.instructions, /Core Thinking/);
});

test("rejects unknown skills", async () => {
  await assert.rejects(() => loadSkill("missing-skill"), /Skill not found/);
});

test("loads profile skills in order, ignores duplicates, and enforces a byte budget", async () => {
  const skills = await loadSkills(["verification", "verification", "core-thinking"], 80);
  assert.deepEqual(skills.map((skill) => skill.name), ["verification"]);
  assert.ok(Buffer.byteLength(skills[0].instructions) <= 80);
});

test("resolves private and project skills without reading them from engine", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-private-skills-"));
  const projectSkills = path.join(root, "projects", "demo", "skills");
  await mkdir(path.join(projectSkills, "project", "project-only"), { recursive: true });
  await writeFile(path.join(projectSkills, "index.json"), JSON.stringify([{
    name: "project-only", description: "Project skill", version: "1.0.0", category: "project",
  }]));
  await writeFile(path.join(projectSkills, "project", "project-only", "SKILL.md"), "Project instructions");
  process.env.ATLAS_ROOT = root;
  const skills = await loadSkills(["project-only"], 1000, path.join(root, "projects", "demo"));
  assert.equal(skills[0].instructions, "Project instructions");
  delete process.env.ATLAS_ROOT;
});

test("the pinned local validator rejects malformed Agent Skills", async () => {
  const script = path.join(process.cwd(), "scripts", "validate-skills.mjs");
  const fixture = path.join(process.cwd(), "tests", "fixtures", "skills", "malformed");
  const child = spawn(process.execPath, [script, fixture], { stdio: ["ignore", "pipe", "pipe"] });
  const output = await new Promise((resolve) => {
    let value = "";
    child.stderr.on("data", (chunk) => { value += chunk; });
    child.on("close", (code) => resolve({ code, value }));
  });
  assert.notEqual(output.code, 0);
  assert.match(output.value, /invalid name/);
});
