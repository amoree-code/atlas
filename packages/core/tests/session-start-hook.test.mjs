import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { OCEAN_BOOTSTRAP_MAX_BYTES } from "../dist/application/context/resource-injection.js";
import {
  claudeNativeHookStatus,
  claudeSessionStartHook,
} from "../dist/application/hooks/session-start-hook.js";
import { SYSTEM_DIR } from "../dist/paths.js";

test("claudeSessionStartHook returns the documented Claude Code hookSpecificOutput shape", async () => {
  const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-outside-"));
  const result = await claudeSessionStartHook({ cwd: outside });
  assert.equal(result.hookSpecificOutput.hookEventName, "SessionStart");
  assert.ok(
    Buffer.byteLength(result.hookSpecificOutput.additionalContext) <=
      OCEAN_BOOTSTRAP_MAX_BYTES,
  );
  assert.match(
    result.hookSpecificOutput.additionalContext,
    /^ocean=1 project=/,
  );
});

test("claudeSessionStartHook reports unbound for a cwd with no Ocean binding, not a guess", async () => {
  const outside = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-unbound-"));
  const oceanRoot = await mkdtemp(path.join(os.tmpdir(), "atlas-hook-root-"));
  const previous = process.env.OCEAN_ROOT;
  process.env.OCEAN_ROOT = oceanRoot;
  try {
    const result = await claudeSessionStartHook({ cwd: outside });
    assert.match(
      result.hookSpecificOutput.additionalContext,
      /project=unbound/,
    );
  } finally {
    if (previous === undefined) delete process.env.OCEAN_ROOT;
    else process.env.OCEAN_ROOT = previous;
  }
});

test("ocean hook session-start CLI: bounded stdout JSON, run from a cwd outside Ocean, no Ocean file content", () => {
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
  assert.ok(
    Buffer.byteLength(parsed.hookSpecificOutput.additionalContext) <= 256,
  );
  assert.doesNotMatch(
    parsed.hookSpecificOutput.additionalContext,
    /MEMORY|KNOWLEDGE|## (?:Atlas|Ocean) resource/,
  );
});

test("ocean hook session-start CLI works with no stdin payload at all (falls back to process cwd)", () => {
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
  const { readBoundedStdin } = await import(
    "../dist/application/hooks/session-start-hook.js"
  );
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
  await mkdir(
    path.join(
      fakeHome,
      "atlas",
      SYSTEM_DIR,
      "integrations",
      "claude-code",
      "hooks",
    ),
    {
      recursive: true,
    },
  );
  await writeFile(
    path.join(
      fakeHome,
      "atlas",
      SYSTEM_DIR,
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
  await mkdir(
    path.join(
      fakeHome,
      "atlas",
      SYSTEM_DIR,
      "integrations",
      "claude-code",
      "hooks",
    ),
    {
      recursive: true,
    },
  );
  const scriptPath = path.join(
    fakeHome,
    "atlas",
    SYSTEM_DIR,
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
      hooks: {
        SessionStart: [{ hooks: [{ type: "command", command: scriptPath }] }],
      },
    }),
  );
  const status = await claudeNativeHookStatus(fakeHome);
  assert.equal(status.registered, true);
});

for (const [folder, hook] of [
  ["ocean", "ocean-session-bootstrap"],
  ["ocean", "atlas-session-bootstrap"],
  ["atlas", "ocean-session-bootstrap"],
]) {
  test(`claudeNativeHookStatus finds ${hook} under ~/${folder} and its registration`, async () => {
    const fakeHome = await mkdtemp(path.join(os.tmpdir(), "ocean-fake-home-"));
    const hooks = path.join(
      fakeHome,
      folder,
      SYSTEM_DIR,
      "integrations",
      "claude-code",
      "hooks",
    );
    await mkdir(hooks, { recursive: true });
    const scriptPath = path.join(hooks, hook);
    await writeFile(scriptPath, "#!/bin/sh\n");
    await mkdir(path.join(fakeHome, ".claude"), { recursive: true });
    await writeFile(
      path.join(fakeHome, ".claude", "settings.json"),
      JSON.stringify({
        hooks: {
          SessionStart: [{ hooks: [{ type: "command", command: scriptPath }] }],
        },
      }),
    );
    const status = await claudeNativeHookStatus(fakeHome);
    assert.equal(status.scriptInstalled, true);
    assert.equal(status.scriptPath, scriptPath);
    assert.equal(status.registered, true);
  });
}

async function hookHome({ script, registered }) {
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "ocean-fake-home-"));
  const hooks = path.join(
    fakeHome,
    "ocean",
    SYSTEM_DIR,
    "integrations",
    "claude-code",
    "hooks",
  );
  await mkdir(hooks, { recursive: true });
  if (script) await writeFile(path.join(hooks, script), "#!/bin/sh\n");
  await mkdir(path.join(fakeHome, ".claude"), { recursive: true });
  await writeFile(
    path.join(fakeHome, ".claude", "settings.json"),
    JSON.stringify({
      hooks: {
        SessionStart: [
          { hooks: [{ type: "command", command: `${hooks}/${registered}` }] },
        ],
      },
    }),
  );
  return fakeHome;
}

test("claudeNativeHookStatus does not count a registration of the other hook name when a script is installed (half-migrated machine)", async () => {
  const status = await claudeNativeHookStatus(
    await hookHome({
      script: "ocean-session-bootstrap",
      registered: "atlas-session-bootstrap",
    }),
  );
  assert.equal(status.scriptInstalled, true);
  assert.equal(status.registered, false);
});

test("claudeNativeHookStatus counts the registration of the installed legacy-named script", async () => {
  const status = await claudeNativeHookStatus(
    await hookHome({
      script: "atlas-session-bootstrap",
      registered: "atlas-session-bootstrap",
    }),
  );
  assert.equal(status.scriptInstalled, true);
  assert.equal(status.registered, true);
});

test("claudeNativeHookStatus still reports a registration under either name when no script is installed", async () => {
  for (const registered of [
    "ocean-session-bootstrap",
    "atlas-session-bootstrap",
  ]) {
    const status = await claudeNativeHookStatus(
      await hookHome({ script: null, registered }),
    );
    assert.equal(status.scriptInstalled, false);
    assert.equal(status.registered, true, registered);
  }
});
