import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { getTicket } from "../dist/application/handoff/handoff-service.js";
import {
  archiveDoneTickets,
  completeTicket,
} from "../dist/application/tickets/archive-tickets.js";

const ticket = (id, state = "done", checklist = "[x]") =>
  `---\nid: ${id}\nproject: atlas\nstate: ${state}\n---\n\nchecklist:\n  - "${checklist} work"\n`;

test("archives verified done tickets and leaves other states live", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ticket-archive-"));
  await mkdir(path.join(root, "T-001"), { recursive: true });
  await mkdir(path.join(root, "T-002"), { recursive: true });
  await mkdir(path.join(root, "T-003"), { recursive: true });
  await writeFile(path.join(root, "T-001", "task.md"), ticket("T-001"));
  await writeFile(
    path.join(root, "T-001", "migration-manifest.md"),
    "manifest",
  );
  await writeFile(
    path.join(root, "T-002", "task.md"),
    ticket("T-002", "active"),
  );
  await writeFile(
    path.join(root, "T-003", "task.md"),
    ticket("T-003", "done", "[ ]"),
  );

  const preview = await archiveDoneTickets(root);
  assert.deepEqual(preview.candidates, ["T-001"]);
  assert.equal(preview.moved.length, 0);
  await access(path.join(root, "T-001", "task.md"));

  const applied = await archiveDoneTickets(root, true);
  assert.deepEqual(applied.moved, ["T-001"]);
  assert.equal(
    await readFile(
      path.join(root, "archive", "Atlas", "T-001", "task.md"),
      "utf8",
    ),
    ticket("T-001"),
  );
  assert.equal(
    await readFile(
      path.join(root, "archive", "Atlas", "T-001", "migration-manifest.md"),
      "utf8",
    ),
    "manifest",
  );
  await access(path.join(root, "T-002", "task.md"));
  await access(path.join(root, "T-003", "task.md"));
});

test("repairs artifacts left by the old task-only archiver", async () => {
  const root = await mkdtemp(
    path.join(os.tmpdir(), "atlas-ticket-archive-repair-"),
  );
  await mkdir(path.join(root, "T-004"), { recursive: true });
  await mkdir(path.join(root, "archive", "Atlas", "T-004"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "archive", "Atlas", "T-004", "task.md"),
    ticket("T-004"),
  );
  await writeFile(
    path.join(root, "T-004", "migration-manifest.md"),
    "legacy artifact",
  );

  const repaired = await archiveDoneTickets(root, true);
  assert.deepEqual(repaired.repaired, ["T-004"]);
  assert.equal(
    await readFile(
      path.join(root, "archive", "Atlas", "T-004", "migration-manifest.md"),
      "utf8",
    ),
    "legacy artifact",
  );
  await assert.rejects(access(path.join(root, "T-004")));
});

test("completes and archives a ticket in one governed transition", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ticket-complete-"));
  await mkdir(path.join(root, "T-005"), { recursive: true });
  await writeFile(
    path.join(root, "T-005", "task.md"),
    ticket("T-005", "active"),
  );
  await writeFile(path.join(root, "T-005", "notes.md"), "preserve me");

  const result = await completeTicket("T-005", root);
  assert.deepEqual(result.moved, ["T-005"]);
  assert.equal(
    await readFile(
      path.join(root, "archive", "Atlas", "T-005", "task.md"),
      "utf8",
    ),
    ticket("T-005"),
  );
  assert.equal(
    await readFile(
      path.join(root, "archive", "Atlas", "T-005", "notes.md"),
      "utf8",
    ),
    "preserve me",
  );
  await assert.rejects(access(path.join(root, "T-005")));
});

test("completion refuses an unchecked ticket without changing it", async () => {
  const root = await mkdtemp(
    path.join(os.tmpdir(), "atlas-ticket-complete-blocked-"),
  );
  await mkdir(path.join(root, "T-006"), { recursive: true });
  const source = ticket("T-006", "active", "[ ]");
  await writeFile(path.join(root, "T-006", "task.md"), source);

  await assert.rejects(completeTicket("T-006", root), /unchecked work/);
  assert.equal(
    await readFile(path.join(root, "T-006", "task.md"), "utf8"),
    source,
  );
});

test("rejects traversal in ticket reads and archive metadata", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ticket-traversal-"));
  const ticketsRoot = path.join(root, "projects", "atlas", "tickets");
  await mkdir(ticketsRoot, { recursive: true });
  await writeFile(path.join(root, "outside.md"), ticket("outside"));
  process.env.ATLAS_ROOT = root;
  try {
    await assert.rejects(
      getTicket("../outside"),
      /Path escapes its allowed root/,
    );
  } finally {
    delete process.env.ATLAS_ROOT;
  }

  await mkdir(path.join(ticketsRoot, "T-007"), { recursive: true });
  await writeFile(
    path.join(ticketsRoot, "T-007", "task.md"),
    ticket("../../outside"),
  );
  await assert.rejects(
    archiveDoneTickets(ticketsRoot, true),
    /Path escapes its allowed root/,
  );

  await mkdir(path.join(ticketsRoot, "T-008"), { recursive: true });
  await writeFile(
    path.join(ticketsRoot, "T-008", "task.md"),
    ticket("T-008").replace("project: atlas", "project: ../../outside"),
  );
  await assert.rejects(
    archiveDoneTickets(ticketsRoot, true),
    /Path escapes its allowed root/,
  );
});
