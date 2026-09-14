import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { appendRuntimeLog, redactRuntimeText } from "../dist/infrastructure/observability/runtime-logger.js";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

test("redacts secrets and private paths while bounding payloads", () => {
  const safe = redactRuntimeText(["sk", "ant", "secret-value"].join("-") + ` ${path.join(os.homedir(), "private.txt")}`);
  assert.doesNotMatch(safe, new RegExp(["sk", "ant", "secret"].join("-")));
  assert.ok(!safe.includes(os.homedir()));
  assert.ok(safe.length <= 64_000);
});

test("redacts generic credentials before applying the payload bound", () => {
  const safe = redactRuntimeText(`Bearer ${"a".repeat(24)} ${["api", "key"].join("_")}=${"b".repeat(16)} ${"x".repeat(70_000)}`);
  assert.doesNotMatch(safe, /Bearer/);
  assert.doesNotMatch(safe, new RegExp(`${["api", "key"].join("_")}=`));
  assert.ok(safe.length <= 64_000);
});

test("writes structured runtime logs outside engine", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-logs-"));
  process.env.ATLAS_ROOT = root;
  await appendRuntimeLog({ timestamp: "2026-09-10T00:00:00.000Z", event: "provider_exit", correlationId: "c1", sessionId: "s1", status: "completed", payload: "ok" });
  const line = await readFile(path.join(root, "system", "runtime", "logs", "runtime.jsonl"), "utf8");
  assert.deepEqual(JSON.parse(line), { timestamp: "2026-09-10T00:00:00.000Z", event: "provider_exit", correlationId: "c1", sessionId: "s1", status: "completed", payload: "ok" });
  delete process.env.ATLAS_ROOT;
});
