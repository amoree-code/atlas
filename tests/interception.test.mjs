import assert from "node:assert/strict";
import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { resolveOriginalExecutable } from "../dist/infrastructure/providers/provider-registry.js";
import { resolveOriginalExecutable as resolveProviderExecutable } from "../dist/infrastructure/providers/provider-registry.js";
import { absolutePathBypassFinding, registerProvider, syncProviderWrappers, installShellIntegration, shellKind, wrapperDoctor } from "../dist/infrastructure/wrappers/wrapper-manager.js";
import { intercept } from "../dist/interfaces/cli/intercept-command.js";
import { openSessionStore } from "../dist/infrastructure/persistence/session-store.js";

async function withEnvironment(run) {
  const root = await import("node:fs/promises").then(({ mkdtemp }) => mkdtemp(path.join(os.tmpdir(), "atlas-intercept-")));
  const oldRoot = process.env.ATLAS_ROOT;
  const oldPath = process.env.PATH;
  const oldShell = process.env.SHELL;
  const oldProfile = process.env.ATLAS_SHELL_PROFILE;
  process.env.ATLAS_ROOT = root;
  process.env.SHELL = "/bin/zsh";
  process.env.ATLAS_SHELL_PROFILE = path.join(root, "profile");
  try {
    await run(root);
  } finally {
    if (oldRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = oldRoot;
    if (oldPath === undefined) delete process.env.PATH; else process.env.PATH = oldPath;
    if (oldShell === undefined) delete process.env.SHELL; else process.env.SHELL = oldShell;
    if (oldProfile === undefined) delete process.env.ATLAS_SHELL_PROFILE; else process.env.ATLAS_SHELL_PROFILE = oldProfile;
  }
}

test("resolves the real provider outside Atlas's shim directory", async () => {
  await withEnvironment(async (root) => {
    const shim = path.join(root, "runtime", "shims");
    const real = path.join(root, "bin");
    await mkdir(shim, { recursive: true });
    await mkdir(real, { recursive: true });
    const executable = path.join(real, "demo-ai");
    await writeFile(executable, "#!/bin/sh\nexit 0\n");
    await chmod(executable, 0o755);
    await writeFile(path.join(shim, "demo-ai"), "shim\n");
    process.env.PATH = `${shim}${path.delimiter}${real}`;
    assert.equal(resolveOriginalExecutable("demo-ai"), executable);
  });
});

test("sync creates Atlas wrappers and shell activation", async () => {
  await withEnvironment(async (root) => {
    const result = await syncProviderWrappers();
    assert.ok(result.providers.some((provider) => provider.id === "claude"));
    const wrapper = await readFile(path.join(root, "runtime", "shims", "claude"), "utf8");
    assert.match(wrapper, /intercept --client/);
    const profile = await installShellIntegration();
    assert.equal(profile, path.join(root, "profile"));
    assert.match(await readFile(profile, "utf8"), /atlas interception/);
  });
});

test("prefers the active parent shell over a stale login-shell environment", () => {
  assert.equal(shellKind("/bin/zsh", "/opt/homebrew/bin/fish"), "posix");
  assert.equal(shellKind("/opt/homebrew/bin/fish", "/bin/zsh"), "fish");
});

test("the generated command wrapper routes the unchanged command through Atlas", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "claude");
    await writeFile(executable, "#!/bin/sh\nif [ \"$1\" = \"auth\" ] && [ \"$2\" = \"status\" ]; then printf '{\"loggedIn\":true}\\n'; exit 0; fi\nprintf 'wrapped-output:%s\\n' \"$1\"\nexit 0\n");
    await chmod(executable, 0o755);
    const { directory } = await syncProviderWrappers();
    const env = { ...process.env, PATH: `${directory}${path.delimiter}${bin}`, ATLAS_ROOT: root };
    const result = spawnSync(path.join(directory, "claude"), ["hello"], { env, encoding: "utf8" });
    assert.equal(result.status, 0, `${result.stderr}\n${result.stdout}`);
    assert.match(result.stdout, /wrapped-output:hello/);
  });
});

test("intercepts a registered CLI and persists the execution", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "demo-ai");
    await writeFile(executable, "#!/bin/sh\nprintf 'demo-output\\n'\nexit 0\n");
    await chmod(executable, 0o755);
    process.env.PATH = `${bin}${path.delimiter}${process.env.PATH}`;
    await registerProvider("demo", "demo-ai");
    const exitCode = await intercept("demo", ["hello"]);
    assert.equal(exitCode, 0);
    const store = await openSessionStore();
    const sessions = store.list();
    assert.equal(sessions.length, 1);
    assert.equal(sessions[0].provider, "demo");
    assert.equal(sessions[0].status, "completed");
    assert.match(store.listEvents(sessions[0].sessionId).map((event) => event.data).join("\n"), /demo-output/);
    store.close();
    assert.equal(resolveProviderExecutable("demo-ai"), executable);
  });
});

test("redacts provider secrets and private paths before session persistence", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "private-ai");
    const providerSecret = ["sk", "-ant-test-secret-value"].join("");
    const inputSecret = ["sk", "-ant-input-secret-value"].join("");
    await writeFile(executable, `#!/bin/sh\nprintf '%s\\n' '${providerSecret} ${os.homedir()}/private.txt'\nprintf '%s\\n' 'done'\n`);
    await chmod(executable, 0o755);
    process.env.PATH = `${bin}${path.delimiter}${process.env.PATH}`;
    await registerProvider("private", "private-ai");
    assert.equal(await intercept("private", [inputSecret]), 0);

    const store = await openSessionStore();
    const events = store.listEvents(store.list()[0].sessionId).map((event) => event.data).join("\n");
    assert.doesNotMatch(events, new RegExp(providerSecret));
    assert.doesNotMatch(events, new RegExp(inputSecret));
    assert.doesNotMatch(events, new RegExp(`${os.homedir().replace(/[.*+?^${}()|[\\]\\\\]/g, "\\\\$&")}/private\\.txt`));
    assert.match(events, /\[REDACTED\]|\[PRIVATE_PATH\]/);
    store.close();
  });
});

test("records missing provider authentication as a bounded block", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "auth-ai");
    await writeFile(executable, "#!/bin/sh\nprintf '401 Unauthorized: sign in to continue\\n'\nexit 1\n");
    await chmod(executable, 0o755);
    process.env.PATH = `${bin}${path.delimiter}${process.env.PATH}`;
    await registerProvider("auth", "auth-ai");
    assert.equal(await intercept("auth", []), 1);

    const store = await openSessionStore();
    const events = store.listEvents(store.list()[0].sessionId).map((event) => event.data).join("\n");
    assert.match(events, /blocked_by_client_authentication/);
    assert.match(events, /provider authentication is required/);
    store.close();
  });
});

test("recovers an authenticated provider failure and resumes the original run once", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "codex");
    await writeFile(executable, `#!/bin/sh
if [ "$1" = "login" ] && [ "$2" = "status" ]; then
  printf 'Logged in\\n'
  exit 0
fi
if [ "$1" = "login" ] && [ "$2" = "--device-auth" ]; then
  touch "$ATLAS_ROOT/recovered"
  exit 0
fi
if [ -f "$ATLAS_ROOT/recovered" ]; then
  printf 'resumed-output\\n'
  exit 0
fi
printf '401 Unauthorized: sign in to continue\\n'
exit 1
`);
    await chmod(executable, 0o755);
    process.env.PATH = `${bin}${path.delimiter}${process.env.PATH}`;
    delete process.env.ATLAS_SANDBOX_RUNTIME;
    assert.equal(await intercept("codex", ["continue"]), 0);

    const store = await openSessionStore();
    const events = store.listEvents(store.list()[0].sessionId);
    assert.ok(events.some((event) => event.type === "auth_recovery_started"));
    assert.ok(events.some((event) => event.type === "run_resumed"));
    assert.match(events.map((event) => event.data).join("\\n"), /resumed-output/);
    store.close();
  });
});

test("doctor reports a shim that is present but ordered after another PATH entry", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "ordered-ai");
    await writeFile(executable, "#!/bin/sh\nexit 0\n");
    await chmod(executable, 0o755);
    await registerProvider("ordered", "ordered-ai");
    process.env.PATH = `${bin}${path.delimiter}${path.join(root, "runtime", "shims")}`;
    const findings = await wrapperDoctor();
    assert.ok(findings.some((finding) => finding.includes("after 1 PATH entries")));
  });
});

test("doctor reports an absolute-path provider bypass", async () => {
  await withEnvironment(async (root) => {
    const bin = path.join(root, "bin");
    await mkdir(bin, { recursive: true });
    const executable = path.join(bin, "direct-ai");
    await writeFile(executable, "#!/bin/sh\nexit 0\n");
    await chmod(executable, 0o755);
    await registerProvider("direct", "direct-ai");
    assert.match(absolutePathBypassFinding(executable), /BYPASS_DETECTED/);
    assert.match((await wrapperDoctor(executable)).join("\n"), /BYPASS_DETECTED/);
  });
});
