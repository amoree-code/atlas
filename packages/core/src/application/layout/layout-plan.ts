import { lstat, readdir, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { workspaceLayout } from "../../paths.js";

// T-243 phase 6: the read-only half of `ocean layout`. It describes the move from the nested
// layout (brain/<area>, kernel/bridge) to the flat one (<area>, bridge) without touching a file,
// so `apply` has one manifest to execute and the owner has one report to read first.

export type LayoutMove = {
  from: string;
  to: string;
  files: number;
  bytes: number;
  symlinks: number;
};

export type LayoutPlan = {
  root: string;
  layout: ReturnType<typeof workspaceLayout>;
  moves: LayoutMove[];
  // A move whose target already exists. Never overwritten: apply refuses while any is listed.
  collisions: { from: string; to: string }[];
  // Top-level entries the target structure does not name, e.g. a stray writer's folder.
  strays: string[];
  // Files that hold the old root-anchored paths and must be repointed at cutover.
  pointers: { file: string; references: number }[];
  gitignore: { from: string | null; to: string }[];
  ready: boolean;
};

const OS_JUNK = new Set([".DS_Store"]);
const RECORD_AREAS = [
  "00-inbox",
  "01-daily",
  "02-personal",
  "03-professional",
  "04-projects",
  "05-knowledge",
  "06-templates",
  "99-archive",
  ".index",
  "charter",
  "INDEX.md",
];
const KNOWN_TOP_LEVEL = new Set([
  ...RECORD_AREAS,
  ...OS_JUNK,
  ".git",
  ".gitignore",
  "README.md",
  "brain",
  "kernel",
  "bridge",
]);

// Client config and shell files outside the root that may point into it. Relative to HOME.
const HOME_POINTERS = [
  ".claude/CLAUDE.md",
  ".claude/AGENTS.md",
  ".claude/settings.json",
  ".claude.json",
  "AGENTS.md",
  ".codex/AGENTS.md",
  ".codex/config.toml",
  ".gemini/GEMINI.md",
  ".gemini/settings.json",
  ".zshrc",
  ".zprofile",
  ".bashrc",
  ".bash_profile",
  ".profile",
  ".config/fish/config.fish",
];
// Folders scanned recursively: shell drop-ins, launchd jobs, and the skill and agent copies each
// client keeps of its own.
const HOME_POINTER_DIRS = [
  ".config/fish/conf.d",
  "Library/LaunchAgents",
  ".claude/skills",
  ".claude/agents",
  ".codex/skills",
  ".gemini/commands",
  ".agents/skills",
];
// Bridge folders that hold data, not configuration; never scanned for pointers.
const BRIDGE_DATA_DIRS = new Set(["sessions", "archive", "browser"]);
const MAX_POINTER_BYTES = 4 * 1024 * 1024;

async function exists(target: string): Promise<boolean> {
  return lstat(target).then(
    () => true,
    () => false,
  );
}

async function entries(directory: string): Promise<string[]> {
  return readdir(directory).catch(() => []);
}

async function measure(
  target: string,
): Promise<Omit<LayoutMove, "from" | "to">> {
  const info = await lstat(target);
  if (info.isSymbolicLink()) return { files: 0, bytes: 0, symlinks: 1 };
  if (!info.isDirectory()) return { files: 1, bytes: info.size, symlinks: 0 };
  const total = { files: 0, bytes: 0, symlinks: 0 };
  for (const name of await entries(target)) {
    const child = await measure(path.join(target, name));
    total.files += child.files;
    total.bytes += child.bytes;
    total.symlinks += child.symlinks;
  }
  return total;
}

async function filesUnder(
  directory: string,
  skip: Set<string> = new Set(),
): Promise<string[]> {
  const found: string[] = [];
  for (const name of await entries(directory)) {
    if (skip.has(name)) continue;
    const target = path.join(directory, name);
    const info = await lstat(target).catch(() => null);
    if (info?.isDirectory()) found.push(...(await filesUnder(target)));
    else if (info?.isFile()) found.push(target);
  }
  return found;
}

// Every spelling a file may use for the old locations: absolute, and HOME-relative when the root
// sits under HOME (~/, $HOME/, ${HOME}/).
export function oldPathNeedles(root: string, home: string): string[] {
  const roots = [root];
  if (root.startsWith(`${home}${path.sep}`)) {
    const relative = path.relative(home, root);
    roots.push(`~/${relative}`, `$HOME/${relative}`, `\${HOME}/${relative}`);
  }
  return roots.flatMap((prefix) => [
    `${prefix}/brain/`,
    `${prefix}/kernel/bridge`,
  ]);
}

function countNeedles(text: string, needles: string[]): number {
  let count = 0;
  for (const needle of needles) count += text.split(needle).length - 1;
  return count;
}

async function pointerFiles(
  home: string,
  bridge: string,
  charter: string,
): Promise<string[]> {
  const candidates = HOME_POINTERS.map((file) => path.join(home, file));
  for (const directory of HOME_POINTER_DIRS)
    candidates.push(...(await filesUnder(path.join(home, directory))));
  candidates.push(...(await filesUnder(bridge, BRIDGE_DATA_DIRS)));
  candidates.push(...(await filesUnder(charter)));
  return [...new Set(candidates)];
}

async function scanPointers(
  root: string,
  home: string,
  layout: LayoutPlan["layout"],
): Promise<LayoutPlan["pointers"]> {
  const needles = oldPathNeedles(root, home);
  const bridge = path.join(
    root,
    layout.bridge === "nested" ? "kernel/bridge" : "bridge",
  );
  const charter = path.join(
    root,
    layout.records === "nested" ? "brain/charter" : "charter",
  );
  const pointers: LayoutPlan["pointers"] = [];
  for (const file of await pointerFiles(home, bridge, charter)) {
    const info = await lstat(file).catch(() => null);
    if (!info?.isFile() || info.size > MAX_POINTER_BYTES) continue;
    const text = await readFile(file, "utf8").catch(() => "");
    if (text.includes("\0")) continue;
    const references = countNeedles(text, needles);
    if (references) pointers.push({ file, references });
  }
  return pointers;
}

async function gitignoreChanges(
  root: string,
): Promise<LayoutPlan["gitignore"]> {
  const source = await readFile(path.join(root, ".gitignore"), "utf8").catch(
    () => null,
  );
  if (source === null) return [];
  const lines = source.split(/\r?\n/);
  const changes: LayoutPlan["gitignore"] = lines
    .filter((line) => /^\/?brain\//.test(line.trim()))
    .map((line) => ({
      from: line,
      to: line.replace(/^(\s*\/?)brain\//, "$1"),
    }));
  if (!lines.some((line) => /^\/?bridge\/?$/.test(line.trim())))
    changes.push({ from: null, to: "/bridge/" });
  return changes;
}

export async function planLayout(
  root: string,
  home: string = os.homedir(),
): Promise<LayoutPlan> {
  const layout = workspaceLayout(root);
  const moves: LayoutMove[] = [];
  const collisions: LayoutPlan["collisions"] = [];
  const addMove = async (from: string, to: string) => {
    moves.push({ from, to, ...(await measure(path.join(root, from))) });
    if (await exists(path.join(root, to))) collisions.push({ from, to });
  };
  if (layout.records === "nested")
    for (const name of (await entries(path.join(root, "brain"))).sort())
      if (!OS_JUNK.has(name)) await addMove(`brain/${name}`, name);
  if (layout.bridge === "nested") await addMove("kernel/bridge", "bridge");

  const strays = (await entries(root))
    .filter((name) => !KNOWN_TOP_LEVEL.has(name))
    .sort();
  return {
    root,
    layout,
    moves,
    collisions,
    strays,
    pointers: await scanPointers(root, home, layout),
    gitignore: moves.length ? await gitignoreChanges(root) : [],
    ready: moves.length > 0 && collisions.length === 0,
  };
}
