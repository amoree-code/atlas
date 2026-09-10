import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import path from "node:path";
import process from "node:process";
import test from "node:test";
import { setTimeout as delay } from "node:timers/promises";

const mainScript = path.join(import.meta.dirname, "..", "dist", "main.js");

test("service stays running until signaled, then exits cleanly", async () => {
  const child = spawn(process.execPath, [mainScript, "service"], { stdio: "pipe" });
  let stdout = "";
  child.stdout.on("data", (chunk) => { stdout += chunk; });

  await delay(300);
  assert.equal(child.exitCode, null, "service exited before receiving a shutdown signal");

  const exited = new Promise((resolve) => child.once("exit", (code) => resolve(code)));
  child.kill("SIGTERM");
  const code = await exited;

  assert.equal(code, 0);
  assert.match(stdout, /Atlas runtime is running/);
  assert.match(stdout, /Atlas runtime stopped/);
});
