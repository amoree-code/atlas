import assert from "node:assert/strict";
import { mkdir, writeFile, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

function validate(root) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [path.join(process.cwd(), "scripts", "validate-tickets.mjs"), root], { stdio: ["ignore", "pipe", "pipe"] });
    let stderr = ""; child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => resolve({ code, stderr }));
  });
}
const ticket = (id, state, checklist = "[x]") => `---\nid: ${id}\ntitle: Test\nstate: ${state}\nproject: test\ngoal: Test\nreferences: [T-001]\n---\n\nchecklist:\n  - "${checklist} work"\n`;

test("ticket validator accepts live plus archived references", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-tickets-"));
  await mkdir(path.join(root, "T-001"), { recursive: true }); await writeFile(path.join(root, "T-001", "task.md"), ticket("T-001", "done"));
  await mkdir(path.join(root, "archive", "T-002"), { recursive: true }); await writeFile(path.join(root, "archive", "T-002", "task.md"), ticket("T-002", "done"));
  const result = await validate(root); assert.equal(result.code, 0);
});
test("ticket validator rejects inconsistent done tickets", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-tickets-invalid-"));
  await mkdir(path.join(root, "T-003"), { recursive: true }); await writeFile(path.join(root, "T-003", "task.md"), ticket("T-003", "done", "[ ]"));
  const result = await validate(root); assert.notEqual(result.code, 0); assert.match(result.stderr, /unchecked work/);
});
