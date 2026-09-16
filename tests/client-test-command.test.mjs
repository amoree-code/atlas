import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

test("client test reports Atlas sources and Claude transport", () => {
  const result = spawnSync(process.execPath, [path.resolve("dist/main.js"), "client", "test", "claude", "--json"], { encoding: "utf8" });
  assert.equal(result.status, 0);
  const report = JSON.parse(result.stdout);
  assert.equal(report.provider, "claude");
  assert.match(report.transport, /bootstrap-env/);
  assert.ok(report.atlas.bootstrapBytes <= 256);
  assert.ok(report.project);
  assert.ok(Array.isArray(report.providerOwnedPaths));
  assert.equal(report.routing.command, "claude");
  assert.match(report.routing.shim, /[\\/]system[\\/]runtime[\\/]shims[\\/]claude(?:\.cmd)?$/);
  assert.match(report.atlas.sessionStore, /[\\/]system[\\/]sessions[\\/]sessions\.sqlite$/);
});

test("client test without a provider reports every registered client", () => {
  const result = spawnSync(process.execPath, [path.resolve("dist/main.js"), "client", "test", "--json"], { encoding: "utf8" });
  assert.equal(result.status, 0);
  const reports = JSON.parse(result.stdout);
  assert.ok(Array.isArray(reports));
  assert.ok(reports.some((report) => report.provider === "claude"));
  assert.ok(reports.some((report) => report.provider === "codex"));
  assert.ok(reports.every((report) => /[\\/]system[\\/]runtime[\\/]shims[\\/]/.test(report.routing.shim)));
});
