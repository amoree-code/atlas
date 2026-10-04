import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { completeTask } from "../dist/application/tasks/archive-tasks.js";
import {
  extractVerificationCommands,
  verifyTask,
} from "../dist/application/tasks/verify-task.js";
import { repoRoot } from "../dist/paths.js";

async function writeTask(root, id, body) {
  const dir = path.join(root, id);
  await mkdir(dir, { recursive: true });
  await writeFile(path.join(dir, "task.md"), body, "utf8");
  return root;
}

const taskBody = (state) => `---
id: T-900
title: "verifier fixture"
state: ${state}
project: atlas
---

## Objective

Prove the verifier gates completion.

## Verification

- \`pnpm build && pnpm test\` green.
- Deliberately break a step and confirm the loop does not report "done".
`;

test("extractVerificationCommands keeps only allowlisted command spans", () => {
  const commands = extractVerificationCommands(taskBody("active"));
  assert.deepEqual(commands, ["pnpm build && pnpm test"]);
});

test("verifyTask passes only when every declared check exits zero", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-verify-"));
  try {
    await writeTask(root, "T-900", taskBody("active"));
    const pass = await verifyTask("T-900", root, {
      run: async () => ({ exitCode: 0 }),
    });
    assert.equal(pass.passed, true);
    assert.equal(pass.checks.length, 1);

    const fail = await verifyTask("T-900", root, {
      run: async () => ({ exitCode: 1 }),
    });
    assert.equal(fail.passed, false);
    assert.match(fail.reason, /verification failed/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("verifyTask refuses a task with no runnable commands", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-verify-"));
  try {
    await writeTask(
      root,
      "T-901",
      `---\nid: T-901\nstate: active\n---\n\n## Verification\n\n- eyeball it\n`,
    );
    const outcome = await verifyTask("T-901", root, {
      run: async () => ({ exitCode: 0 }),
    });
    assert.equal(outcome.passed, false);
    assert.match(outcome.reason, /no runnable verification/);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("completeTask with verify refuses when the independent check fails", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-verify-"));
  try {
    await writeTask(root, "T-900", taskBody("active"));
    await assert.rejects(
      completeTask("T-900", root, {
        verify: true,
        run: async () => ({ exitCode: 1 }),
      }),
      /Cannot complete T-900/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("completeTask with verify succeeds when the independent check passes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-verify-"));
  try {
    await writeTask(root, "T-900", taskBody("active"));
    const result = await completeTask("T-900", root, {
      verify: true,
      run: async () => ({ exitCode: 0 }),
    });
    assert.equal(result.state, "done");
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("verifyTask defaults its working directory to the engine repo root", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-verify-"));
  try {
    await writeTask(root, "T-900", taskBody("active"));
    let seen = "";
    await verifyTask("T-900", root, {
      run: async (_command, cwd) => {
        seen = cwd;
        return { exitCode: 0 };
      },
    });
    assert.equal(seen, repoRoot());
    assert.ok(existsSync(seen));
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
