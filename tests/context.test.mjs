import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";

test("context returns a compact JSON packet without loading ticket bodies", () => {
  const result = spawnSync(process.execPath, [path.resolve("dist/main.js"), "context", "--json"], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const packet = JSON.parse(result.stdout);
  assert.equal(packet.project, "atlas");
  assert.equal(packet.version, "0.3.6");
  assert.deepEqual(packet.roots, ["personal", "projects", "system"]);
  assert.ok(Array.isArray(packet.tickets));
});
