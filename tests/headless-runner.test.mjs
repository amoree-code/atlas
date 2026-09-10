import assert from "node:assert/strict";
import process from "node:process";
import test from "node:test";
import { runHeadless } from "../dist/infrastructure/process/cli-process.js";

test("streams structured and plain headless output", async () => {
  const result = await runHeadless({
    command: process.execPath,
    args: ["-e", "console.log(JSON.stringify({type:'delta',text:'ok'})); console.log('done')"],
    cwd: process.cwd(),
  });

  assert.equal(result.exitCode, 0);
  assert.deepEqual(result.events, [
    { type: "json", data: { type: "delta", text: "ok" } },
    { type: "text", data: "done" },
  ]);
});

test("terminates a headless process that exceeds its limit", async () => {
  const result = await runHeadless({
    command: process.execPath,
    args: ["-e", "setTimeout(() => {}, 5000)"],
    cwd: process.cwd(),
    timeoutMs: 10,
  });

  assert.equal(result.exitCode, 124);
  assert.match(result.stderr, /timed out/);
});

test("terminates a headless process that exceeds its output budget", async () => {
  const result = await runHeadless({
    command: process.execPath,
    args: ["-e", "console.log('0123456789')"],
    cwd: process.cwd(),
    maxOutputBytes: 4,
  });

  assert.equal(result.exitCode, 125);
  assert.match(result.stderr, /Output budget exceeded/);
});
