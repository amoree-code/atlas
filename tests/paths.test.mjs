import assert from "node:assert/strict";
import { mkdir, mkdtemp, symlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  atlasPath,
  atlasRoot,
  enginePath,
  engineRoot,
  resolveWithin,
} from "../dist/paths.js";

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
    assert.equal(
      atlasPath("personal"),
      path.join(path.resolve(override), "personal"),
    );
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
    assert.equal(
      enginePath("dist", "main.js"),
      path.join(engineRoot(), "dist", "main.js"),
    );
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});

test("resolveWithin allows an ordinary path inside its root, existing or not", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resolve-within-"));
  await writeFile(path.join(root, "existing.txt"), "hi");
  assert.equal(
    resolveWithin(root, "existing.txt"),
    path.join(root, "existing.txt"),
  );
  assert.equal(
    resolveWithin(root, "not-yet-created", "target.txt"),
    path.join(root, "not-yet-created", "target.txt"),
  );
});

test("resolveWithin rejects lexical traversal out of its root", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resolve-within-"));
  assert.throws(
    () => resolveWithin(root, "..", "outside.txt"),
    /Path escapes its allowed root/,
  );
});

test("resolveWithin rejects a symlink inside its root that points outside it", async () => {
  const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-outside-"));
  await writeFile(path.join(outside, "secret.txt"), "secret");
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resolve-within-"));
  await symlink(outside, path.join(root, "escape-link"));

  assert.throws(
    () => resolveWithin(root, "escape-link", "secret.txt"),
    /Path escapes its allowed root/,
  );
});

test("resolveWithin allows a symlink inside its root that points elsewhere inside it", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-resolve-within-"));
  await mkdir(path.join(root, "real-target"));
  await writeFile(path.join(root, "real-target", "file.txt"), "hi");
  await symlink(
    path.join(root, "real-target"),
    path.join(root, "internal-link"),
  );

  assert.doesNotThrow(() => resolveWithin(root, "internal-link", "file.txt"));
});
