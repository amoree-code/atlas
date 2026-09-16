import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ATLAS_BOOTSTRAP_MAX_BYTES } from "../dist/application/context/resource-injection.js";
import {
  claudeNativeHookStatus,
  claudeSessionStartHook,
} from "../dist/application/hooks/session-start-hook.js";

test("claudeSessionStartHook returns the documented Claude Code hookSpecificOutput shape", async () => {
  const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-outside-"));
  const result = await claudeSessionStartHook({ cwd: outside });
  assert.equal(result.hookSpecificOutput.hookEventName, "SessionStart");
  assert.ok(
    Buffer.byteLength(result.hookSpecificOutput.additionalContext) <= ATLAS_BOOTSTRAP_MAX_BYTES,
  );
  assert.match(result.hookSpecificOutput.additionalContext, /^atlas=1 project=/);
});

test("claudeSessionStartHook reports unbound for a cwd with no Atlas binding, not a guess", async () => {
  const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-unbound-"));
  const atlasRoot = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-root-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = atlasRoot;
  try {
    const result = await claudeSessionStartHook({ cwd: outside });
    assert.match(result.hookSpecificOutput.additionalContext, /project=unbound/);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previous;
  }
});

test("atlas hook session-start CLI: bounded stdout JSON, run from a cwd outside Atlas, no Atlas file content", () => {
  const outside = os.tmpdir();
  const payload = JSON.stringify({
    cwd: outside,
    session_id: "cli-test",
    hook_event_name: "SessionStart",
  });
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "hook", "session-start"],
    { input: payload, encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout.trim());
  assert.equal(parsed.hookSpecificOutput.hookEventName, "SessionStart");
  assert.ok(Buffer.byteLength(parsed.hookSpecificOutput.additionalContext) <= 256);
  assert.doesNotMatch(
    parsed.hookSpecificOutput.additionalContext,
    /MEMORY|KNOWLEDGE|## Atlas resource/,
  );
});

test("atlas hook session-start CLI works with no stdin payload at all (falls back to process cwd)", () => {
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "hook", "session-start"],
    { input: "", encoding: "utf8" },
  );
  assert.equal(result.status, 0, result.stderr);
  const parsed = JSON.parse(result.stdout.trim());
  assert.equal(parsed.hookSpecificOutput.hookEventName, "SessionStart");
});

test("readBoundedStdin rejects a payload larger than its bound instead of buffering it unbounded", async () => {
  const { readBoundedStdin } = await import("../dist/application/hooks/session-start-hook.js");
  const { Readable } = await import("node:stream");
  const oversized = Readable.from([Buffer.alloc(200, "x")]);
  oversized.isTTY = false;
  await assert.rejects(() => readBoundedStdin(oversized, 100), /exceeds/);
});

test("claudeNativeHookStatus reports not-installed/not-registered honestly when neither exists", async () => {
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-fake-home-"));
  const status = await claudeNativeHookStatus(fakeHome);
  assert.equal(status.scriptInstalled, false);
  assert.equal(status.registered, false);
});

test("claudeNativeHookStatus reports installed-but-not-registered when the script exists but settings.json does not reference it", async () => {
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-fake-home-"));
  await mkdir(path.join(fakeHome, "atlas", "system", "integrations", "claude-code", "hooks"), {
    recursive: true,
  });
  await writeFile(
    path.join(
      fakeHome,
      "atlas",
      "system",
      "integrations",
      "claude-code",
      "hooks",
      "atlas-session-bootstrap",
    ),
    "#!/bin/sh\n",
  );
  await mkdir(path.join(fakeHome, ".claude"), { recursive: true });
  await writeFile(
    path.join(fakeHome, ".claude", "settings.json"),
    JSON.stringify({ hooks: { SessionStart: [] } }),
  );
  const status = await claudeNativeHookStatus(fakeHome);
  assert.equal(status.scriptInstalled, true);
  assert.equal(status.registered, false);
});

test("claudeNativeHookStatus reports registered only when settings.json actually references the script", async () => {
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-fake-home-"));
  await mkdir(path.join(fakeHome, "atlas", "system", "integrations", "claude-code", "hooks"), {
    recursive: true,
  });
  const scriptPath = path.join(
    fakeHome,
    "atlas",
    "system",
    "integrations",
    "claude-code",
    "hooks",
    "atlas-session-bootstrap",
  );
  await writeFile(scriptPath, "#!/bin/sh\n");
  await mkdir(path.join(fakeHome, ".claude"), { recursive: true });
  await writeFile(
    path.join(fakeHome, ".claude", "settings.json"),
    JSON.stringify({
      hooks: { SessionStart: [{ hooks: [{ type: "command", command: scriptPath }] }] },
    }),
  );
  const status = await claudeNativeHookStatus(fakeHome);
  assert.equal(status.registered, true);
});
