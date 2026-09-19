import { execFile as execFileCallback } from "node:child_process";
import {
  access,
  chmod,
  mkdir,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { atlasPath, enginePath } from "../../paths.js";
import {
  builtInProviderRecords,
  loadProviderRegistry,
  type ProviderRecord,
  resolveOriginalExecutable,
  saveProviderRegistry,
} from "../providers/provider-registry.js";

const execFile = promisify(execFileCallback);

export function shimDirectory(): string {
  return atlasPath("system", "runtime", "shims");
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\\''")}'`;
}

function wrapperPath(command: string): string {
  return process.platform === "win32"
    ? path.join(shimDirectory(), `${command}.cmd`)
    : path.join(shimDirectory(), command);
}

export function providerWrapperPath(command: string): string {
  return wrapperPath(command);
}

export function desktopWrapperPath(provider = "claude"): string {
  return wrapperPath(`${provider}-vscode`);
}

function wrapperContents(provider: ProviderRecord): string {
  const node = shellQuote(process.execPath);
  const entry = shellQuote(enginePath("dist", "main.js"));
  if (process.platform === "win32") {
    return `@echo off\r\nset "ATLAS_SHIM_DIR=${shimDirectory()}"\r\n"${process.execPath}" "${enginePath("dist", "main.js")}" intercept --client "${provider.id}" -- %*\r\n`;
  }
  return `#!/bin/sh\nexport ATLAS_SHIM_DIR=${shellQuote(shimDirectory())}\nexec ${node} ${entry} intercept --client ${shellQuote(provider.id)} -- "$@"\n`;
}

function atlasWrapperContents(): string {
  if (process.platform === "win32") {
    return `@echo off\r\n"${process.execPath}" "${enginePath("dist", "main.js")}" %*\r\n`;
  }
  return `#!/bin/sh\nexec ${shellQuote(process.execPath)} ${shellQuote(enginePath("dist", "main.js"))} "$@"\n`;
}

function desktopWrapperContents(provider: string): string {
  if (process.platform === "win32") {
    return `@echo off\r\nif "%~1"=="" exit /b 64\r\nset "native=%~1"\r\nshift\r\n"${process.execPath}" "${enginePath("dist", "main.js")}" intercept --client "${provider}" --executable "%native%" -- %*\r\n`;
  }
  return `#!/bin/sh
if [ "$#" -lt 1 ]; then
  echo "Atlas desktop wrapper requires the native ${provider} executable path" >&2
  exit 64
fi
native="$1"
shift
exec ${shellQuote(process.execPath)} ${shellQuote(enginePath("dist", "main.js"))} intercept --client ${shellQuote(provider)} --executable "$native" -- "$@"
`;
}

export async function syncProviderWrappers(): Promise<{
  providers: ProviderRecord[];
  directory: string;
}> {
  const providers = loadProviderRegistry();
  await mkdir(shimDirectory(), { recursive: true });
  const atlasWrapper = wrapperPath("atlas");
  await writeFile(atlasWrapper, atlasWrapperContents());
  if (process.platform !== "win32") await chmod(atlasWrapper, 0o755);
  for (const provider of providers) {
    const file = wrapperPath(provider.command);
    await writeFile(file, wrapperContents(provider));
    if (process.platform !== "win32") await chmod(file, 0o755);
  }
  const desktopWrapper = desktopWrapperPath("claude");
  await writeFile(desktopWrapper, desktopWrapperContents("claude"));
  if (process.platform !== "win32") await chmod(desktopWrapper, 0o755);
  await saveProviderRegistry(providers);
  return { providers, directory: shimDirectory() };
}

export async function registerProvider(
  id: string,
  command = id,
): Promise<ProviderRecord> {
  if (!/^[a-zA-Z0-9._-]+$/.test(id) || !/^[a-zA-Z0-9._-]+$/.test(command)) {
    throw new Error(
      "Provider id and command may contain only letters, numbers, dot, underscore, and hyphen",
    );
  }
  const providers = loadProviderRegistry().filter(
    (provider) => provider.id !== id,
  );
  const provider: ProviderRecord = {
    id,
    command,
    interactive: true,
    headless: true,
  };
  await saveProviderRegistry([...providers, provider]);
  await syncProviderWrappers();
  return provider;
}

export async function removeProvider(id: string): Promise<ProviderRecord> {
  const providers = loadProviderRegistry();
  const provider = providers.find(
    (candidate) => candidate.id === id || candidate.command === id,
  );
  if (!provider) throw new Error(`Provider is not registered: ${id}`);
  if (
    builtInProviderRecords().some((candidate) => candidate.id === provider.id)
  ) {
    throw new Error(
      `Built-in provider remains registered; use its package manager to remove: ${provider.id}`,
    );
  }
  await rm(wrapperPath(provider.command), { force: true });
  await saveProviderRegistry(
    providers.filter((candidate) => candidate.id !== provider.id),
  );
  return provider;
}

export function shellKind(
  parentCommand: string,
  loginShell: string,
): "fish" | "posix" {
  const parent = path.basename(parentCommand.trim().split(/\s+/, 1)[0] ?? "");
  if (parent === "fish") return "fish";
  if (["ash", "bash", "dash", "ksh", "sh", "zsh"].includes(parent))
    return "posix";
  return path.basename(loginShell) === "fish" ? "fish" : "posix";
}

async function currentShellName(): Promise<string> {
  if (process.platform === "win32") return "powershell";
  try {
    const { stdout } = await execFile("ps", [
      "-p",
      String(process.ppid),
      "-o",
      "comm=",
    ]);
    const parent = path.basename(stdout.trim().split(/\s+/, 1)[0] ?? "");
    if (["ash", "bash", "dash", "fish", "ksh", "sh", "zsh"].includes(parent))
      return parent;
  } catch {
    // Fall through to the configured login shell.
  }
  return path.basename(process.env.SHELL ?? "");
}

async function currentShellKind(): Promise<"fish" | "posix"> {
  return (await currentShellName()) === "fish" ? "fish" : "posix";
}

export async function installShellPath(): Promise<string> {
  const directory = shimDirectory();
  if (process.platform === "win32") {
    return `$env:Path = "${directory};$env:Path"`;
  }
  if ((await currentShellKind()) === "fish") {
    return `fish_add_path --global --prepend --move ${shellQuote(directory)}`;
  }
  return `export PATH=${shellQuote(directory)}:$PATH`;
}

async function shellProfilePath(): Promise<string> {
  const home = os.homedir();
  if (process.platform === "win32")
    return (
      process.env.ATLAS_SHELL_PROFILE ??
      path.join(
        home,
        "Documents",
        "PowerShell",
        "Microsoft.PowerShell_profile.ps1",
      )
    );
  if (process.env.ATLAS_SHELL_PROFILE) return process.env.ATLAS_SHELL_PROFILE;
  const shell = await currentShellName();
  if (shell === "fish")
    return path.join(home, ".config", "fish", "config.fish");
  if (shell === "zsh") return path.join(home, ".zshrc");
  if (shell === "bash") return path.join(home, ".bashrc");
  return path.join(home, ".profile");
}

export async function installShellIntegration(): Promise<string> {
  const file = await shellProfilePath();
  const marker =
    /\n?# >>> atlas interception >>>[\s\S]*?# <<< atlas interception <<<\n?/;
  let existing = "";
  try {
    existing = await readFile(file, "utf8");
  } catch {
    /* new profile */
  }
  const line = await installShellPath();
  const block = `\n# >>> atlas interception >>>\n${line}\n# <<< atlas interception <<<\n`;
  await mkdir(path.dirname(file), { recursive: true });
  await writeFile(file, existing.replace(marker, "\n") + block);
  return file;
}

export async function wrapperDoctor(commandPath?: string): Promise<string[]> {
  const findings: string[] = [];
  const providers = loadProviderRegistry();
  try {
    const contents = await readFile(wrapperPath("atlas"), "utf8");
    if (!contents.includes("dist/main.js"))
      findings.push(
        "atlas: CLI wrapper is stale or does not route through Atlas",
      );
  } catch {
    findings.push(`atlas: CLI wrapper is missing at ${wrapperPath("atlas")}`);
  }
  for (const provider of providers) {
    try {
      const contents = await readFile(wrapperPath(provider.command), "utf8");
      if (
        !contents.includes(`intercept --client '${provider.id}'`) &&
        !contents.includes(`intercept --client "${provider.id}"`)
      ) {
        findings.push(
          `${provider.id}: wrapper is stale or does not route through Atlas`,
        );
      }
    } catch {
      findings.push(
        `${provider.id}: wrapper is missing at ${wrapperPath(provider.command)}`,
      );
    }
    try {
      resolveOriginalExecutable(provider.command);
    } catch (error) {
      findings.push(
        `${provider.id}: ${error instanceof Error ? error.message : String(error)}`,
      );
    }
  }
  const currentPath = (process.env.PATH ?? "")
    .split(path.delimiter)
    .map((entry) => path.resolve(entry));
  const index = currentPath.indexOf(path.resolve(shimDirectory()));
  if (index < 0)
    findings.push(`Atlas shim directory is not on PATH: ${shimDirectory()}`);
  else if (index > 0)
    findings.push(
      `Atlas shim directory is after ${index} PATH entries; provider commands can bypass Atlas`,
    );
  const bypass = commandPath ? absolutePathBypassFinding(commandPath) : null;
  if (bypass) findings.push(bypass);
  return findings;
}

export function absolutePathBypassFinding(commandPath: string): string | null {
  if (!path.isAbsolute(commandPath)) return null;
  const resolved = path.resolve(commandPath);
  if (resolved.startsWith(`${path.resolve(shimDirectory())}${path.sep}`))
    return null;
  const command = path.basename(resolved).replace(/\.(cmd|exe|bat)$/i, "");
  const provider = loadProviderRegistry().find(
    (candidate) => candidate.command === command,
  );
  if (!provider)
    return `BYPASS_DETECTED: absolute path is outside Atlas and is not a registered provider: ${resolved}`;
  return `BYPASS_DETECTED: ${provider.id} was invoked by absolute path outside Atlas shims: ${resolved}`;
}

export async function wrapperStatus(): Promise<
  Array<
    ProviderRecord & {
      wrapper: string;
      installed: boolean;
      realExecutable: string | null;
      entryPoint: "terminal-shim";
      controlLevel: "observed";
    }
  >
> {
  const providers = loadProviderRegistry();
  return Promise.all(
    providers.map(async (provider) => {
      let realExecutable: string | null = null;
      try {
        realExecutable = resolveOriginalExecutable(provider.command);
      } catch {
        /* reported by doctor */
      }
      let installed = true;
      try {
        await access(wrapperPath(provider.command));
      } catch {
        installed = false;
      }
      return {
        ...provider,
        wrapper: wrapperPath(provider.command),
        installed,
        realExecutable,
        entryPoint: "terminal-shim",
        controlLevel: "observed",
      };
    }),
  );
}
