import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { archiveDoneTickets } from "../dist/application/tickets/archive-tickets.js";

const ticket = (id, state = "done", checklist = "[x]") => `---\nid: ${id}\nproject: atlas\nstate: ${state}\n---\n\nchecklist:\n  - "${checklist} work"\n`;

test("archives verified done tickets and leaves other states live", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ticket-archive-"));
  await mkdir(path.join(root, "T-001"), { recursive: true });
  await mkdir(path.join(root, "T-002"), { recursive: true });
  await mkdir(path.join(root, "T-003"), { recursive: true });
  await writeFile(path.join(root, "T-001", "task.md"), ticket("T-001"));
  await writeFile(path.join(root, "T-001", "migration-manifest.md"), "manifest");
  await writeFile(path.join(root, "T-002", "task.md"), ticket("T-002", "active"));
  await writeFile(path.join(root, "T-003", "task.md"), ticket("T-003", "done", "[ ]"));

  const preview = await archiveDoneTickets(root);
  assert.deepEqual(preview.candidates, ["T-001"]);
  assert.equal(preview.moved.length, 0);
  await access(path.join(root, "T-001", "task.md"));

  const applied = await archiveDoneTickets(root, true);
  assert.deepEqual(applied.moved, ["T-001"]);
  assert.equal(await readFile(path.join(root, "archive", "Atlas", "T-001", "task.md"), "utf8"), ticket("T-001"));
  assert.equal(await readFile(path.join(root, "archive", "Atlas", "T-001", "migration-manifest.md"), "utf8"), "manifest");
  await access(path.join(root, "T-002", "task.md"));
  await access(path.join(root, "T-003", "task.md"));
});

test("repairs artifacts left by the old task-only archiver", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ticket-archive-repair-"));
  await mkdir(path.join(root, "T-004"), { recursive: true });
  await mkdir(path.join(root, "archive", "Atlas", "T-004"), { recursive: true });
  await writeFile(path.join(root, "archive", "Atlas", "T-004", "task.md"), ticket("T-004"));
  await writeFile(path.join(root, "T-004", "migration-manifest.md"), "legacy artifact");

  const repaired = await archiveDoneTickets(root, true);
  assert.deepEqual(repaired.repaired, ["T-004"]);
  assert.equal(await readFile(path.join(root, "archive", "Atlas", "T-004", "migration-manifest.md"), "utf8"), "legacy artifact");
  await assert.rejects(access(path.join(root, "T-004")));
});
