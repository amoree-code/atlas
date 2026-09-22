import assert from "node:assert/strict";
import { mkdtemp, readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { runObserveCommand } from "../dist/interfaces/cli/observe-command.js";

async function withAtlasRoot(fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-observe-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    await fn(root);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previous;
  }
}

test("atlas observe redacts secrets in captured output before writing to disk", async () => {
  await withAtlasRoot(async (root) => {
    const secretToken = `sk-ant-${"a".repeat(20)}`;
    await runObserveCommand([
      "--",
      process.execPath,
      "-e",
      `console.log(${JSON.stringify(secretToken)})`,
    ]);
    const observationsDir = path.join(root, "system", "observations");
    const [file] = await readdir(observationsDir);
    const observation = JSON.parse(
      await readFile(path.join(observationsDir, file), "utf8"),
    );
    assert.ok(!observation.stdout.includes(secretToken));
    assert.match(observation.stdout, /\[REDACTED\]/);
  });
});
