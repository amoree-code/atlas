import {
  chmod,
  copyFile,
  mkdir,
  readFile,
  stat,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { desktopWrapperPath } from "../../infrastructure/wrappers/wrapper-manager.js";

export function defaultClaudeCodeSettingsPath(): string {
  if (process.platform === "darwin")
    return path.join(
      os.homedir(),
      "Library",
      "Application Support",
      "Code",
      "User",
      "settings.json",
    );
  if (process.platform === "win32")
    return path.join(
      process.env.APPDATA ?? path.join(os.homedir(), "AppData", "Roaming"),
      "Code",
      "User",
      "settings.json",
    );
  return path.join(os.homedir(), ".config", "Code", "User", "settings.json");
}

export async function configureClaudeCodeWrapper(
  settingsPath = defaultClaudeCodeSettingsPath(),
  apply = false,
): Promise<{
  settingsPath: string;
  wrapper: string;
  apply: boolean;
  changed: boolean;
  backup: string | null;
}> {
  const wrapper = desktopWrapperPath("claude");
  let source = "{}\n";
  try {
    source = await readFile(settingsPath, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  let settings: Record<string, unknown>;
  try {
    settings = JSON.parse(source) as Record<string, unknown>;
  } catch {
    throw new Error(
      `Claude Code settings must be plain JSON for automatic setup: ${settingsPath}`,
    );
  }
  const changed = settings["claudeCode.claudeProcessWrapper"] !== wrapper;
  if (!apply || !changed)
    return { settingsPath, wrapper, apply, changed, backup: null };

  await mkdir(path.dirname(settingsPath), { recursive: true });
  let backup: string | null = null;
  try {
    const metadata = await stat(settingsPath);
    backup = `${settingsPath}.atlas-backup-${new Date().toISOString().replace(/[:.]/g, "-")}`;
    await copyFile(settingsPath, backup);
    await writeFile(
      settingsPath,
      `${JSON.stringify({ ...settings, "claudeCode.claudeProcessWrapper": wrapper }, null, 2)}\n`,
      "utf8",
    );
    await chmod(settingsPath, metadata.mode & 0o777);
  } catch (error) {
    if (backup) throw error;
    await writeFile(
      settingsPath,
      `${JSON.stringify({ ...settings, "claudeCode.claudeProcessWrapper": wrapper }, null, 2)}\n`,
      "utf8",
    );
  }
  return { settingsPath, wrapper, apply, changed, backup };
}
