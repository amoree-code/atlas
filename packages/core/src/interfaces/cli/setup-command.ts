import {
  chmod,
  mkdir,
  readdir,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { connectObsidianVault } from "../../application/obsidian/vault-discovery.js";
import { registryFile } from "../../fs-utils.js";
import {
  installShellIntegration,
  syncProviderWrappers,
} from "../../infrastructure/wrappers/wrapper-manager.js";
import {
  DAILY_DIR,
  enginePath,
  INBOX_DIR,
  KNOWLEDGE_DIR,
  oceanPath,
  oceanRoot,
  PERSONAL_DIR,
  PROJECTS_DIR,
  projectFolder,
  REGISTRY_DIR,
  SYSTEM_DIR,
  TEMPLATES_DIR,
  WORKSPACE_PROJECT_ID,
} from "../../paths.js";

const personalDirectories = [
  PERSONAL_DIR,
  KNOWLEDGE_DIR,
  DAILY_DIR,
  INBOX_DIR,
  TEMPLATES_DIR,
];

const REGISTRY_FILES = [
  "providers.json",
  "installations.json",
  "project-bindings.json",
];

const stateDirectories = [
  `${SYSTEM_DIR}/config/startup`,
  `${SYSTEM_DIR}/profiles`,
  `${SYSTEM_DIR}/sessions`,
  REGISTRY_DIR,
  `${SYSTEM_DIR}/integrations`,
  `${SYSTEM_DIR}/archive`,
  `${SYSTEM_DIR}/runtime/shims`,
  `${SYSTEM_DIR}/runtime/temporary`,
];

async function ensureFile(file: string, contents: string): Promise<void> {
  try {
    await writeFile(file, contents, { flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
}

async function restrictDirectories(directory: string): Promise<void> {
  await chmod(directory, 0o700);
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory())
      await restrictDirectories(path.join(directory, entry.name));
  }
}

// Startup entries were named "atlas" before the rename. Setup writes the Ocean-named entry and
// reports a leftover legacy one; it never deletes or unloads it, so a running service is not
// pulled out from under the user and the two never start side by side unnoticed.
async function legacyStartupEntry(file: string): Promise<string | null> {
  try {
    await stat(file);
    return file;
  } catch {
    return null;
  }
}

async function installMacStartup(): Promise<string | null> {
  const launchAgents = path.join(os.homedir(), "Library", "LaunchAgents");
  const label = "com.ocean.runtime";
  const plist = path.join(launchAgents, `${label}.plist`);
  const node = process.execPath;
  const entry = enginePath("dist", "main.js");
  const contents = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${node}</string><string>${entry}</string><string>service</string></array>
<key>WorkingDirectory</key><string>${oceanRoot()}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
</dict></plist>
`;
  await mkdir(launchAgents, { recursive: true });
  await writeFile(plist, contents);
  return legacyStartupEntry(path.join(launchAgents, "com.atlas.runtime.plist"));
}

async function installLinuxStartup(): Promise<string | null> {
  const systemdUser = path.join(os.homedir(), ".config", "systemd", "user");
  const unit = path.join(systemdUser, "ocean.service");
  const contents = `[Unit]
Description=Ocean local runtime

[Service]
Type=simple
WorkingDirectory=${oceanRoot()}
ExecStart=${process.execPath} ${enginePath("dist", "main.js")} service
Restart=on-failure

[Install]
WantedBy=default.target
`;
  await mkdir(systemdUser, { recursive: true });
  await writeFile(unit, contents);
  return legacyStartupEntry(path.join(systemdUser, "atlas.service"));
}

async function installWindowsStartup(): Promise<string | null> {
  const startup = path.join(
    process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "Startup",
  );
  const launcher = path.join(startup, "ocean.cmd");
  const contents = `@echo off\ncd /d "${oceanRoot()}"\n"${process.execPath}" "${enginePath("dist", "main.js")}" service\n`;
  await mkdir(startup, { recursive: true });
  await writeFile(launcher, contents);
  return legacyStartupEntry(path.join(startup, "atlas.cmd"));
}

export type SetupOptions = {
  obsidianPath?: string;
  obsidianMode?: "read-only" | "read-write";
};

export async function setup(options: SetupOptions = {}): Promise<void> {
  await Promise.all(
    [
      ...personalDirectories,
      // Where the workspace project's tasks live today ("atlas/" until the layout migration),
      // never a second, empty folder that would hide them.
      `${PROJECTS_DIR}/${projectFolder(WORKSPACE_PROJECT_ID)}/tasks`,
    ].map((directory) => mkdir(oceanPath(directory), { recursive: true })),
  );
  for (const file of REGISTRY_FILES) registryFile(file);
  await Promise.all(
    stateDirectories.map((directory) =>
      mkdir(oceanPath(directory), { recursive: true }),
    ),
  );
  await ensureFile(
    oceanPath(PERSONAL_DIR, "MEMORY.md"),
    "# Memory\n\n## Records (generated)\n",
  );
  await ensureFile(
    oceanPath(KNOWLEDGE_DIR, "KNOWLEDGE.md"),
    "# Knowledge\n\n## Records (generated)\n",
  );
  await ensureFile(
    oceanPath(SYSTEM_DIR, "profiles", "default.json"),
    await readFile(
      new URL("../../../templates/profiles/default.json", import.meta.url),
      "utf8",
    ),
  );
  await ensureFile(
    oceanPath(SYSTEM_DIR, "config", "startup", "STARTUP.md"),
    "# Ocean startup\n\nManaged by `ocean setup`.\n",
  );
  await syncProviderWrappers();
  const shellProfile = await installShellIntegration();

  let legacyStartup: string | null = null;
  if (process.platform === "darwin") legacyStartup = await installMacStartup();
  if (process.platform === "linux") legacyStartup = await installLinuxStartup();
  if (process.platform === "win32")
    legacyStartup = await installWindowsStartup();
  if (legacyStartup)
    console.warn(
      `Legacy startup entry still present: ${legacyStartup}. Remove it (and unload it if loaded) so the Ocean runtime does not start twice.`,
    );
  await restrictDirectories(oceanPath(SYSTEM_DIR));
  if (options.obsidianPath) {
    const result = await connectObsidianVault(
      options.obsidianPath,
      options.obsidianMode ?? "read-only",
    );
    console.log(
      `Obsidian connected: ${result.vaultPath} (${result.noteCount} Markdown notes)`,
    );
  }
  console.log(
    `Ocean setup complete: ${oceanRoot()} (AI CLI interception enabled in ${shellProfile})`,
  );
}
