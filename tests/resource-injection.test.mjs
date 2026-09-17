import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ATLAS_BOOTSTRAP_MAX_BYTES, bootstrapEnvironment, buildAtlasBootstrap } from "../dist/application/context/resource-injection.js";
import { bindProject, resolveProject } from "../dist/application/context/project-resolution.js";

async function withTempAtlasRoot(fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-bootstrap-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    return await fn(root);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previous;
  }
}

test("bound project bootstrap stays within the 256-byte budget and carries no Atlas file content", () => {
  const bootstrap = buildAtlasBootstrap({ status: "bound", projectId: "atlas", name: "Atlas", path: "/x", matchedOn: "atlas-root", confidence: "high" });
  assert.ok(bootstrap.manifest.bytes <= ATLAS_BOOTSTRAP_MAX_BYTES, `${bootstrap.manifest.bytes} exceeds ${ATLAS_BOOTSTRAP_MAX_BYTES}`);
  assert.equal(bootstrap.manifest.transport, "bootstrap-env");
  assert.match(bootstrap.content, /project=atlas/);
  assert.doesNotMatch(bootstrap.content, /##\s*Atlas resource/);
});

test("unbound project bootstrap reports unbound rather than guessing a project", () => {
  const bootstrap = buildAtlasBootstrap({ status: "unbound", cwd: "/tmp/somewhere", gitRoot: null, confidence: "none" });
  assert.match(bootstrap.content, /project=unbound/);
  assert.match(bootstrap.content, /confidence=none/);
});

test("bootstrap is delivered only as environment variables, never as file content or provider args", () => {
  const bootstrap = buildAtlasBootstrap({ status: "unbound", cwd: "/tmp", gitRoot: null, confidence: "none" });
  const env = bootstrapEnvironment(bootstrap);
  assert.equal(env.ATLAS_BOOTSTRAP, bootstrap.content);
  assert.equal(Object.keys(env).length, 2);
  assert.ok(Buffer.byteLength(env.ATLAS_BOOTSTRAP) <= ATLAS_BOOTSTRAP_MAX_BYTES);
});

test("resolveProject reports unbound for an arbitrary cwd with no binding and no git root", async () => {
  await withTempAtlasRoot(async (root) => {
    const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-outside-"));
    const resolution = await resolveProject(outside);
    assert.equal(resolution.status, "unbound");
  });
});

test("resolveProject resolves a cwd inside the Atlas root itself to the atlas project", async () => {
  await withTempAtlasRoot(async (root) => {
    const resolution = await resolveProject(root);
    assert.equal(resolution.status, "bound");
    assert.equal(resolution.projectId, "atlas");
    assert.equal(resolution.confidence, "high");
  });
});

test("bindProject creates a binding and resolveProject then finds it from that exact cwd", async () => {
  await withTempAtlasRoot(async () => {
    const projectDir = await mkdtemp(path.join(os.tmpdir(), "atlas-project-"));
    const bound = await bindProject("demo", projectDir);
    assert.equal(bound.created, true);
    assert.equal(bound.conflict, undefined);
    const resolution = await resolveProject(projectDir);
    assert.equal(resolution.status, "bound");
    assert.equal(resolution.projectId, "demo");
    assert.equal(resolution.matchedOn, "cwd");
  });
});

test("resolveProject uses the deepest containing binding from a non-Git subdirectory", async () => {
  await withTempAtlasRoot(async () => {
    const projectDir = await mkdtemp(path.join(os.tmpdir(), "atlas-project-nested-"));
    await bindProject("demo", projectDir);
    const nested = path.join(projectDir, "src", "components");
    const { mkdir } = await import("node:fs/promises");
    await mkdir(nested, { recursive: true });
    const resolution = await resolveProject(nested);
    assert.equal(resolution.status, "bound");
    assert.equal(resolution.projectId, "demo");
    assert.equal(resolution.matchedOn, "path");
  });
});

test("bindProject reports a conflict instead of silently overwriting an existing binding", async () => {
  await withTempAtlasRoot(async () => {
    const projectDir = await mkdtemp(path.join(os.tmpdir(), "atlas-project-"));
    await bindProject("demo", projectDir);
    const second = await bindProject("other-name", projectDir);
    assert.equal(second.created, false);
    assert.ok(second.conflict);
    assert.equal(second.conflict.name, "demo");
  });
});

test("bindProject repeated with the same name and path is idempotent, not a conflict", async () => {
  await withTempAtlasRoot(async () => {
    const projectDir = await mkdtemp(path.join(os.tmpdir(), "atlas-project-"));
    await bindProject("demo", projectDir);
    const second = await bindProject("demo", projectDir);
    assert.equal(second.created, false);
    assert.equal(second.conflict, undefined);
  });
});
