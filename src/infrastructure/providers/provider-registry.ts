import { accessSync, constants, existsSync, readFileSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export type ProviderRecord = {
  id: string;
  command: string;
  interactive: boolean;
  headless: boolean;
};

const builtInProviders: ProviderRecord[] = [
  { id: "claude", command: "claude", interactive: true, headless: true },
  { id: "codex", command: "codex", interactive: true, headless: true },
  { id: "gemini", command: "gemini", interactive: true, headless: true },
  { id: "antigravity", command: "agy", interactive: true, headless: true },
];

export const providerRegistryPath = (): string => atlasPath("control-plane", "registry", "providers.json");

export function builtInProviderRecords(): ProviderRecord[] {
  return builtInProviders.map((provider) => ({ ...provider }));
}

export function loadProviderRegistry(): ProviderRecord[] {
  const file = providerRegistryPath();
  if (!existsSync(file)) return builtInProviderRecords();
  const parsed = JSON.parse(readFileSync(file, "utf8")) as { providers?: ProviderRecord[] };
  const custom = Array.isArray(parsed.providers) ? parsed.providers : [];
  const merged = new Map<string, ProviderRecord>();
  for (const provider of [...builtInProviders, ...custom]) merged.set(provider.id, provider);
  return [...merged.values()];
}

export async function saveProviderRegistry(providers: ProviderRecord[]): Promise<void> {
  await mkdir(path.dirname(providerRegistryPath()), { recursive: true });
  await writeFile(providerRegistryPath(), `${JSON.stringify({ version: 1, providers }, null, 2)}\n`);
}

export function findProvider(value: string, providers = loadProviderRegistry()): ProviderRecord {
  const provider = providers.find((candidate) => candidate.id === value || candidate.command === value);
  if (!provider) throw new Error(`Provider is not registered: ${value}`);
  return provider;
}

export function resolveOriginalExecutable(command: string, env = process.env): string {
  const shimRoot = path.resolve(env.ATLAS_SHIM_DIR ?? atlasPath("runtime", "shims"));
  const pathEntries = (env.PATH ?? "").split(path.delimiter).filter(Boolean);
  const names = process.platform === "win32" ? [command, `${command}.exe`, `${command}.cmd`, `${command}.bat`] : [command];

  for (const directory of pathEntries) {
    if (path.resolve(directory) === shimRoot) continue;
    for (const name of names) {
      const candidate = path.join(directory, name);
      try {
        accessSync(candidate, constants.X_OK);
        return candidate;
      } catch {
        // Continue through PATH until the first executable outside Atlas's shim directory.
      }
    }
  }
  throw new Error(`Provider executable not found outside Atlas shims: ${command}`);
}
