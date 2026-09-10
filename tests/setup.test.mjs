import assert from "node:assert/strict";
import { mkdtemp, readFile, stat } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { setup } from "../dist/interfaces/cli/setup-command.js";
import { enginePath } from "../dist/paths.js";

function platformStartupFile(home) {
  if (process.platform === "darwin") {
    return path.join(home, "Library", "LaunchAgents", "com.atlas.runtime.plist");
  }
  if (process.platform === "linux") {
    return path.join(home, ".config", "systemd", "user", "atlas.service");
  }
  return path.join(home, "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "atlas.cmd");
}

test("setup isolates its writes to ATLAS_ROOT and the (fake) home directory, never the engine tree", async () => {
  const privateRoot = await mkdtemp(path.join(os.tmpdir(), "atlas-setup-root-"));
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-setup-home-"));

  const originalAtlasRoot = process.env.ATLAS_ROOT;
  const originalHome = process.env.HOME;
  const originalAppData = process.env.APPDATA;
  process.env.ATLAS_ROOT = privateRoot;
  process.env.HOME = fakeHome;
  if (process.platform === "win32") process.env.APPDATA = path.join(fakeHome, "AppData", "Roaming");

  try {
    await setup();

    for (const directory of ["personal/memory"]) {
      const info = await stat(path.join(privateRoot, directory));
      assert.ok(info.isDirectory(), `expected ${directory} under the private root`);
    }
    for (const directory of ["profiles", "sessions", "config/startup", "control-plane", "integrations", "archive"]) {
      const info = await stat(path.join(privateRoot, directory));
      assert.ok(info.isDirectory(), `expected ${directory} under the private root`);
    }
    await stat(path.join(privateRoot, "config", "settings.json"));
    await stat(path.join(privateRoot, "profiles", "default.json"));

    const startupFile = platformStartupFile(fakeHome);
    const contents = await readFile(startupFile, "utf8");
    assert.ok(contents.includes(enginePath("dist", "main.js")), "startup entry should point at the engine executable");
    assert.ok(contents.includes(privateRoot), "startup entry should use the private root as its working directory");
  } finally {
    if (originalAtlasRoot === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = originalAtlasRoot;
    if (originalHome === undefined) delete process.env.HOME; else process.env.HOME = originalHome;
    if (originalAppData === undefined) delete process.env.APPDATA; else process.env.APPDATA = originalAppData;
  }
});
