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
  PROJECTS_DIR,
  SYSTEM_DIR,
} from "../dist/paths.js";

function platformStartupFile(home) {
  if (process.platform === "darwin") {
    return path.join(
      home,
      "Library",
      "LaunchAgents",
      "com.ocean.runtime.plist",
    );
  }
  if (process.platform === "linux") {
    return path.join(home, ".config", "systemd", "user", "ocean.service");
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
    "ocean.cmd",
  );
}

test("setup isolates its writes to OCEAN_ROOT and the (fake) home directory, never the engine tree", async () => {
  const privateRoot = await mkdtemp(
    path.join(os.tmpdir(), "atlas-setup-root-"),
  );
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "atlas-setup-home-"));

  const originalAtlasRoot = process.env.OCEAN_ROOT;
  const originalHome = process.env.HOME;
  const originalAppData = process.env.APPDATA;
  process.env.OCEAN_ROOT = privateRoot;
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
    if (originalAtlasRoot === undefined) delete process.env.OCEAN_ROOT;
    else process.env.OCEAN_ROOT = originalAtlasRoot;
    if (originalHome === undefined) delete process.env.HOME;
    else process.env.HOME = originalHome;
    if (originalAppData === undefined) delete process.env.APPDATA;
    else process.env.APPDATA = originalAppData;
  }
});

function legacyStartupFile(home) {
  return platformStartupFile(home)
    .replace("com.ocean.runtime", "com.atlas.runtime")
    .replace("ocean.service", "atlas.service")
    .replace("ocean.cmd", "atlas.cmd");
}

test("setup reports a leftover pre-rename startup entry and leaves it in place", async () => {
  const privateRoot = await mkdtemp(
    path.join(os.tmpdir(), "ocean-setup-root-"),
  );
  const fakeHome = await mkdtemp(path.join(os.tmpdir(), "ocean-setup-home-"));
  const legacy = legacyStartupFile(fakeHome);
  await mkdir(path.dirname(legacy), { recursive: true });
  await writeFile(legacy, "legacy\n");
  const saved = {
    root: process.env.OCEAN_ROOT,
    home: process.env.HOME,
    appData: process.env.APPDATA,
  };
  process.env.OCEAN_ROOT = privateRoot;
  process.env.HOME = fakeHome;
  if (process.platform === "win32")
    process.env.APPDATA = path.join(fakeHome, "AppData", "Roaming");
  const warnings = [];
  const originalWarn = console.warn;
  console.warn = (message) => warnings.push(String(message));
  try {
    await setup();
  } finally {
    console.warn = originalWarn;
    for (const [key, name] of [
      ["root", "OCEAN_ROOT"],
      ["home", "HOME"],
      ["appData", "APPDATA"],
    ]) {
      if (saved[key] === undefined) delete process.env[name];
      else process.env[name] = saved[key];
    }
  }
  assert.equal(await readFile(legacy, "utf8"), "legacy\n");
  assert.ok(
    warnings.some((message) => message.includes(legacy)),
    warnings.join("|"),
  );
  await stat(platformStartupFile(fakeHome));
});

async function setupAt(root, prepare) {
  const fakeHome = await mkdtemp(
    path.join(os.tmpdir(), "ocean-setup-folder-home-"),
  );
  if (prepare) await prepare(root);
  const saved = {
    root: process.env.OCEAN_ROOT,
    home: process.env.HOME,
    appData: process.env.APPDATA,
  };
  process.env.OCEAN_ROOT = root;
  process.env.HOME = fakeHome;
  if (process.platform === "win32")
    process.env.APPDATA = path.join(fakeHome, "AppData", "Roaming");
  try {
    await setup();
  } finally {
    for (const [key, name] of [
      ["root", "OCEAN_ROOT"],
      ["home", "HOME"],
      ["appData", "APPDATA"],
    ]) {
      if (saved[key] === undefined) delete process.env[name];
      else process.env[name] = saved[key];
    }
  }
}

test("setup creates the workspace project's tasks folder as ocean/ on a fresh root", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ocean-setup-fresh-"));
  await setupAt(root);
  await stat(path.join(root, PROJECTS_DIR, "ocean", "tasks"));
  await assert.rejects(stat(path.join(root, PROJECTS_DIR, "atlas")));
});

test("setup on a machine that still has atlas/tasks keeps using it and creates no second, empty ocean/ folder", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "ocean-setup-legacy-"));
  await setupAt(root, (r) =>
    mkdir(path.join(r, PROJECTS_DIR, "atlas", "tasks"), { recursive: true }),
  );
  await stat(path.join(root, PROJECTS_DIR, "atlas", "tasks"));
  await assert.rejects(stat(path.join(root, PROJECTS_DIR, "ocean")));
});
