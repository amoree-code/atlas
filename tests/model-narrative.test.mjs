import assert from "node:assert/strict";
import test from "node:test";
import { generateModelNarrative, isTrivialSession } from "../dist/application/memory/model-narrative.js";

test("isTrivialSession is true with no changed files and no substantial provider output", () => {
  assert.equal(isTrivialSession([], []), true);
  assert.equal(isTrivialSession([{ type: "provider_output", data: "ok" }], []), true);
  assert.equal(isTrivialSession([], ["src/file.ts"]), false);
  assert.equal(isTrivialSession([{ type: "provider_output", data: "a".repeat(50) }], []), false);
});

test("generateModelNarrative never calls the model unless ATLAS_MODEL_NARRATIVE=1 (cost is opt-in, off by default)", async () => {
  delete process.env.ATLAS_MODEL_NARRATIVE;
  const session = { workingDirectory: "/tmp/example", title: "Example session" };
  const events = [{ type: "provider_output", data: "a".repeat(60) }];
  const result = await generateModelNarrative({ session, events, changedFiles: ["src/file.ts"] });
  assert.equal(result, null);
});

test("generateModelNarrative skips recursively when already inside a narrative-generation call", async () => {
  process.env.ATLAS_MODEL_NARRATIVE = "1";
  process.env.ATLAS_NARRATIVE_CALL = "1";
  try {
    const session = { workingDirectory: "/tmp/example", title: "Example session" };
    const events = [{ type: "provider_output", data: "a".repeat(60) }];
    const result = await generateModelNarrative({ session, events, changedFiles: ["src/file.ts"] });
    assert.equal(result, null);
  } finally {
    delete process.env.ATLAS_MODEL_NARRATIVE;
    delete process.env.ATLAS_NARRATIVE_CALL;
  }
});
