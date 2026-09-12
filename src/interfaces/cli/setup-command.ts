import { chmod, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { atlasPath, atlasRoot, enginePath } from "../../paths.js";
import { installShellIntegration, syncProviderWrappers } from "../../infrastructure/wrappers/wrapper-manager.js";

const personalDirectories = [
  "personal/memory",
  "personal/knowledge",
  "personal/daily",
  "personal/inbox",
  "personal/templates",
  "projects/atlas/tickets",
];

const stateDirectories = [
  "config/policies",
  "config/schemas",
  "config/startup",
  "profiles",
  "sessions",
  "control-plane",
  "integrations",
  "archive",
];

async function ensureFile(file: string, contents: string): Promise<void> {
  try {
    await writeFile(file, contents, { flag: "wx" });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
  }
}

async function installMacStartup(): Promise<void> {
  const launchAgents = path.join(os.homedir(), "Library", "LaunchAgents");
  const label = "com.atlas.runtime";
  const plist = path.join(launchAgents, `${label}.plist`);
  const node = process.execPath;
  const entry = enginePath("dist", "main.js");
  const contents = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${label}</string>
<key>ProgramArguments</key><array><string>${node}</string><string>${entry}</string><string>service</string></array>
<key>WorkingDirectory</key><string>${atlasRoot()}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
</dict></plist>
`;
  await mkdir(launchAgents, { recursive: true });
  await writeFile(plist, contents);
}

async function installLinuxStartup(): Promise<void> {
  const systemdUser = path.join(os.homedir(), ".config", "systemd", "user");
  const unit = path.join(systemdUser, "atlas.service");
  const contents = `[Unit]
Description=Atlas local runtime

[Service]
Type=simple
WorkingDirectory=${atlasRoot()}
ExecStart=${process.execPath} ${enginePath("dist", "main.js")} service
Restart=on-failure

[Install]
WantedBy=default.target
`;
  await mkdir(systemdUser, { recursive: true });
  await writeFile(unit, contents);
}

async function installWindowsStartup(): Promise<void> {
  const startup = path.join(
    process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming"),
    "Microsoft",
    "Windows",
    "Start Menu",
    "Programs",
    "Startup",
  );
  const launcher = path.join(startup, "atlas.cmd");
  const contents = `@echo off\ncd /d "${atlasRoot()}"\n"${process.execPath}" "${enginePath("dist", "main.js")}" service\n`;
  await mkdir(startup, { recursive: true });
  await writeFile(launcher, contents);
}

export async function setup(): Promise<void> {
  await Promise.all(personalDirectories.map((directory) => mkdir(atlasPath(directory), { recursive: true })));
  await Promise.all(stateDirectories.map((directory) => mkdir(atlasPath(directory), { recursive: true })));
  await ensureFile(atlasPath("config", "settings.json"), await readFile(new URL("../../../templates/config/settings.json", import.meta.url), "utf8"));
  await ensureFile(atlasPath("profiles", "default.json"), await readFile(new URL("../../../templates/profiles/default.json", import.meta.url), "utf8"));
  await ensureFile(atlasPath("config", "startup", "README.md"), "# Atlas startup\n\nManaged by `atlas setup`.\n");
  await syncProviderWrappers();
  const shellProfile = await installShellIntegration();

  if (process.platform === "darwin") await installMacStartup();
  if (process.platform === "linux") await installLinuxStartup();
  if (process.platform === "win32") await installWindowsStartup();
  await chmod(atlasPath("config"), 0o700);
  console.log(`Atlas setup complete: ${atlasRoot()} (AI CLI interception enabled in ${shellProfile})`);
}
