import assert from "node:assert/strict";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { atlasPath, atlasRoot, enginePath, engineRoot } from "../dist/paths.js";

test("engineRoot resolves to the engine package directory, one level above this module", () => {
  assert.equal(engineRoot(), path.resolve(import.meta.dirname, ".."));
});

test("default atlasRoot resolves to the private workspace sibling of engine, not inside it", () => {
  delete process.env.ATLAS_ROOT;
  assert.equal(atlasRoot(), path.resolve(engineRoot(), ".."));
  assert.notEqual(atlasRoot(), engineRoot());
});

test("ATLAS_ROOT explicitly overrides the default private root", () => {
  const override = path.join(os.tmpdir(), "atlas-root-override");
  process.env.ATLAS_ROOT = override;
  try {
    assert.equal(atlasRoot(), path.resolve(override));
    assert.equal(atlasPath("personal"), path.join(path.resolve(override), "personal"));
    assert.equal(
      atlasPath("sessions", "sessions.sqlite"),
      path.join(path.resolve(override), "sessions", "sessions.sqlite"),
    );
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("enginePath always resolves relative to engine root, ignoring ATLAS_ROOT", () => {
  process.env.ATLAS_ROOT = path.join(os.tmpdir(), "atlas-root-unrelated");
  try {
    assert.equal(enginePath("dist", "main.js"), path.join(engineRoot(), "dist", "main.js"));
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});
