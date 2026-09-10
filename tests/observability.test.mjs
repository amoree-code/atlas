import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { appendRuntimeLog, redactRuntimeText } from "../dist/infrastructure/observability/runtime-logger.js";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

test("redacts secrets and private paths while bounding payloads", () => {
  const safe = redactRuntimeText(`sk-ant-secret-value ${path.join(os.homedir(), "private.txt")}`);
  assert.doesNotMatch(safe, /sk-ant-secret/);
  assert.ok(!safe.includes(os.homedir()));
  assert.ok(safe.length <= 64_000);
});

test("writes structured runtime logs outside engine", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-logs-"));
  process.env.ATLAS_ROOT = root;
  await appendRuntimeLog({ timestamp: "2026-09-10T00:00:00.000Z", event: "provider_exit", correlationId: "c1", sessionId: "s1", status: "completed", payload: "ok" });
  const line = await readFile(path.join(root, "logs", "runtime.jsonl"), "utf8");
  assert.deepEqual(JSON.parse(line), { timestamp: "2026-09-10T00:00:00.000Z", event: "provider_exit", correlationId: "c1", sessionId: "s1", status: "completed", payload: "ok" });
  delete process.env.ATLAS_ROOT;
});
