import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  listTaskLoops,
  startTaskLoop,
  stopTaskLoop,
} from "../dist/application/loops/task-loop.js";

test("task loop persists bounded state and stops explicitly", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-loop-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const loop = await startTaskLoop({
      taskId: "T-213",
      profile: "researcher",
      prompt: "Work one bounded action",
      cwd: root,
      approved: true,
      maxIterations: 3,
      intervalMs: 1_000,
      maxAttempts: 2,
    });
    assert.equal((await listTaskLoops()).length, 1);
    assert.equal(loop.maxIterations, 3);
    assert.equal((await stopTaskLoop(loop.id)).status, "stopped");
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previous;
    await rm(root, { recursive: true, force: true });
  }
});
