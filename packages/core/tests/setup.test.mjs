import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { setup } from "../dist/interfaces/cli/setup-command.js";
import {
  enginePath,
  KNOWLEDGE_DIR,
  PERSONAL_DIR,
  SYSTEM_DIR,
} from "../dist/paths.js";

function platformStartupFile(home) {
  if (process.platform === "darwin") {
    return path.join(
      home,
      "Library",
      "LaunchAgents",
      "com.atlas.runtime.plist",
    );
  }
  if (process.platform === "linux") {
    return path.join(home, ".config", "systemd", "user", "atlas.service");
  }
  return path.join(
    home,
    "AppData",
    "Roaming",
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "Startup",
    "atlas.cmd",
  );
}

test("setup isolates its writes to ATLAS_ROOT and the (fake) home directory, never the engine tree", async () => {
  const privateRoot = await mkdtemp(
    path.join(os.tmpdir(), "atlas-setup-root-"),
  );
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-setup-home-"));

  const originalAtlasRoot = process.env.ATLAS_ROOT;
  const originalHome = process.env.HOME;
  const originalAppData = process.env.APPDATA;
  process.env.ATLAS_ROOT = privateRoot;
  process.env.HOME = fakeHome;
  if (process.platform === "win32")
    process.env.APPDATA = path.join(fakeHome, "AppData", "Roaming");

  try {
    await setup();

    for (const directory of [PERSONAL_DIR]) {
      const info = await stat(path.join(privateRoot, directory));
      assert.ok(
        info.isDirectory(),
        `expected ${directory} under the private root`,
      );
    }
    await stat(path.join(privateRoot, PERSONAL_DIR, "MEMORY.md"));
    await stat(path.join(privateRoot, KNOWLEDGE_DIR, "KNOWLEDGE.md"));
    for (const directory of [
      `${SYSTEM_DIR}/profiles`,
      `${SYSTEM_DIR}/sessions`,
      `${SYSTEM_DIR}/config/startup`,
      `${SYSTEM_DIR}/registry`,
      `${SYSTEM_DIR}/integrations`,
      `${SYSTEM_DIR}/archive`,
    ]) {
      const info = await stat(path.join(privateRoot, directory));
      assert.ok(
        info.isDirectory(),
        `expected ${directory} under the private root`,
      );
    }
    await stat(path.join(privateRoot, SYSTEM_DIR, "profiles", "default.json"));
    await assert.rejects(
      stat(
        path.join(
          privateRoot,
          SYSTEM_DIR,
          "profiles",
          "default",
          "profile.json",
        ),
      ),
    );

    const startupFile = platformStartupFile(fakeHome);
    const contents = await readFile(startupFile, "utf8");
    assert.ok(
      contents.includes(enginePath("dist", "main.js")),
      "startup entry should point at the engine executable",
    );
    assert.ok(
      contents.includes(privateRoot),
      "startup entry should use the private root as its working directory",
    );
  } finally {
    if (originalAtlasRoot === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = originalAtlasRoot;
    if (originalHome === undefined) delete process.env.HOME;
    else process.env.HOME = originalHome;
    if (originalAppData === undefined) delete process.env.APPDATA;
    else process.env.APPDATA = originalAppData;
  }
});

test("setup moves a legacy control-plane registry to the registry directory once", async () => {
  const privateRoot = await mkdtemp(
    path.join(os.tmpdir(), "atlas-setup-registry-"),
  );
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-setup-home-"));
  const originalAtlasRoot = process.env.ATLAS_ROOT;
  const originalHome = process.env.HOME;
  const originalAppData = process.env.APPDATA;
  process.env.ATLAS_ROOT = privateRoot;
  process.env.HOME = fakeHome;
  if (process.platform === "win32")
    process.env.APPDATA = path.join(fakeHome, "AppData", "Roaming");

  const legacy = path.join(
    privateRoot,
    SYSTEM_DIR,
    "control-plane",
    "registry",
  );
  try {
    await mkdir(legacy, { recursive: true });
    await writeFile(path.join(legacy, "marker.txt"), "legacy\n");

    await setup();

    const moved = path.join(privateRoot, SYSTEM_DIR, "registry", "marker.txt");
    assert.equal(await readFile(moved, "utf8"), "legacy\n");
    await assert.rejects(stat(legacy));

    await setup();
    assert.equal(await readFile(moved, "utf8"), "legacy\n");
  } finally {
    if (originalAtlasRoot === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = originalAtlasRoot;
    if (originalHome === undefined) delete process.env.HOME;
    else process.env.HOME = originalHome;
    if (originalAppData === undefined) delete process.env.APPDATA;
    else process.env.APPDATA = originalAppData;
  }
});
