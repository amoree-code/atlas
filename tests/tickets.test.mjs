import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

function validate(root) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [path.join(process.cwd(), "scripts", "validate-tickets.mjs"), root],
      { stdio: ["ignore", "pipe", "pipe"] },
    );
    let stderr = "";
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("close", (code) => resolve({ code, stderr }));
  });
}
const ticket = (id, state, checklist = "[x]") =>
  `---\nid: ${id}\ntitle: Test\nstate: ${state}\nproject: test\ngoal: Test\nreferences: [T-001]\n---\n\nchecklist:\n  - "${checklist} work"\n`;

test("ticket validator accepts live plus archived references", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-tickets-"));
  await mkdir(path.join(root, "T-001"), { recursive: true });
  await writeFile(path.join(root, "T-001", "task.md"), ticket("T-001", "done"));
  await mkdir(path.join(root, "archive", "T-002"), { recursive: true });
  await writeFile(
    path.join(root, "archive", "T-002", "task.md"),
    ticket("T-002", "done"),
  );
  const result = await validate(root);
  assert.equal(result.code, 0);
});
test("ticket validator rejects inconsistent done tickets", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-tickets-invalid-"));
  await mkdir(path.join(root, "T-003"), { recursive: true });
  await writeFile(
    path.join(root, "T-003", "task.md"),
    ticket("T-003", "done", "[ ]"),
  );
  const result = await validate(root);
  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /unchecked work/);
});

test("tickets list returns live ticket summaries and filters by state", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-tickets-list-"));
  await mkdir(path.join(root, "projects", "atlas", "tickets", "T-001"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "projects", "atlas", "tickets", "T-001", "task.md"),
    "---\nid: T-001\ntitle: First\nstate: active\ngoal: Test goal\nupdated_at: 2026-09-13\n---\n",
  );
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "tickets", "list", "active"],
    { env: { ...process.env, ATLAS_ROOT: root }, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), [
    {
      id: "T-001",
      title: "First",
      state: "active",
      goal: "Test goal",
      updatedAt: "2026-09-13",
    },
  ]);
});

test("tickets list reads the selected project instead of Atlas only", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-project-tickets-"));
  await mkdir(path.join(root, "projects", "frontend", "tickets", "T-101"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "projects", "frontend", "tickets", "T-101", "task.md"),
    "---\nid: T-101\ntitle: Frontend\nstate: active\ngoal: Ship UI\n---\n",
  );
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const { listTickets } = await import(
      "../dist/interfaces/cli/tickets-command.js"
    );
    assert.deepEqual(
      (await listTickets(undefined, "frontend")).map((item) => item.id),
      ["T-101"],
    );
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previous;
  }
});
