import { createHash } from "node:crypto";
import {
  chmod,
  copyFile,
  cp,
  lstat,
  mkdir,
  readdir,
  readFile,
  readlink,
  realpath,
  rename,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { type LayoutPlan, oldPathPattern, planLayout } from "./layout-plan.js";

// T-243 phase 6: the writing half of `ocean layout`. It copies — never moves — each old tree to
// its flat location through a staging folder, repoints the files the plan found, and keeps a
// journal and byte-for-byte backups so `rollback` can put every pointer back. The old trees are
// never written or deleted here; removing them is the owner's step once the new layout is proven.

const STAGING = ".layout-staging";
const BACKUPS = ".ocean-layout-backups";
// The records' sentinel arrives last, so a reader never takes a half-copied flat tree as current.
const LAST = "04-projects";

type Manifest = Record<string, string>;
type PointerBackup = {
  file: string;
  kind: "file" | "symlink";
  // file: the backup copy's name inside the backup folder; symlink: the old link target.
  backup: string;
};
export type LayoutJournal = {
  version: 1;
  root: string;
  home: string;
  startedAt: string;
  step: "snapshotted" | "copied" | "swapped" | "done" | "rolled-back";
  moves: { from: string; to: string }[];
  pointers: PointerBackup[];
  gitignore: string | null;
  // The new trees as apply left them (after repointing), keyed by move target.
  manifests: Record<string, Manifest>;
};

async function exists(target: string): Promise<boolean> {
  return lstat(target).then(
    () => true,
    () => false,
  );
}

// Every entry under a tree: files by sha256, symlinks by their target, directories as such.
async function manifest(target: string): Promise<Manifest> {
  const entries: Manifest = {};
  const walk = async (current: string, relative: string) => {
    const info = await lstat(current);
    if (info.isSymbolicLink())
      entries[relative] = `link:${await readlink(current)}`;
    else if (info.isDirectory()) {
      entries[relative] = "dir";
      for (const name of (await readdir(current)).sort())
        await walk(path.join(current, name), path.posix.join(relative, name));
    } else
      entries[relative] = `sha256:${createHash("sha256")
        .update(await readFile(current))
        .digest("hex")}`;
  };
  await walk(target, ".");
  return entries;
}

function differences(expected: Manifest, actual: Manifest): string[] {
  const keys = new Set([...Object.keys(expected), ...Object.keys(actual)]);
  return [...keys].filter((key) => expected[key] !== actual[key]).sort();
}

async function writeAtomic(file: string, content: string): Promise<void> {
  // Write through a symlinked dotfile to the file it names, so the link itself survives.
  const target = await realpath(file).catch(() => file);
  const mode = (await stat(target)).mode & 0o7777;
  const temporary = `${target}.ocean-layout-${process.pid}`;
  await writeFile(temporary, content, { mode });
  await chmod(temporary, mode);
  await rename(temporary, target);
}

async function replaceLink(link: string, target: string): Promise<void> {
  const temporary = `${link}.ocean-layout-${process.pid}`;
  await symlink(target, temporary);
  await rename(temporary, link);
}

// `<p>/brain/x` → `<p>/x` and `<p>/kernel/bridge/x` → `<p>/bridge/x`, by the plan's own pattern.
export function repoint(text: string, root: string, home: string): string {
  return text.replace(oldPathPattern(root, home), (_, prefix, area) =>
    area === "brain" ? prefix : `${prefix}/bridge`,
  );
}

// A pointer inside an old tree is rewritten in its new copy; the old tree is left untouched.
function newLocation(
  file: string,
  root: string,
  moves: LayoutJournal["moves"],
): string {
  for (const { from, to } of moves) {
    const old = path.join(root, from);
    if (file === old || file.startsWith(`${old}${path.sep}`))
      return path.join(root, to, path.relative(old, file));
  }
  return file;
}

function insideOldTree(
  file: string,
  root: string,
  moves: LayoutJournal["moves"],
): boolean {
  return newLocation(file, root, moves) !== file;
}

function applyGitignore(source: string, plan: LayoutPlan): string {
  const lines = source.split(/\r?\n/);
  const newline = source.includes("\r\n") ? "\r\n" : "\n";
  for (const change of plan.gitignore) {
    if (change.from === null) continue;
    const index = lines.indexOf(change.from);
    if (index < 0) continue;
    if (change.to === null) lines.splice(index, 1);
    else lines[index] = change.to;
  }
  const additions = plan.gitignore
    .filter((change) => change.from === null && change.to !== null)
    .map((change) => change.to as string);
  if (additions.length) {
    if (lines.at(-1) === "") lines.pop();
    lines.push(...additions, "");
  }
  return lines.join(newline);
}

async function writeJournal(
  backup: string,
  journal: LayoutJournal,
): Promise<void> {
  await writeFile(
    path.join(backup, "journal.json"),
    `${JSON.stringify(journal, null, 2)}\n`,
    { mode: 0o600 },
  );
}

export type ApplyResult = {
  applied: boolean;
  reason: string;
  backup?: string;
  moved?: string[];
  repointed?: number;
};

export async function applyLayout(
  root: string,
  home: string = os.homedir(),
): Promise<ApplyResult> {
  const staging = path.join(root, STAGING);
  if (await exists(staging))
    throw new Error(
      `${staging} exists: an earlier apply was interrupted. Run \`ocean layout rollback\` first.`,
    );
  const plan = await planLayout(root, home);
  if (!plan.moves.length)
    return { applied: false, reason: "nothing to move: already flat" };
  if (!plan.ready)
    throw new Error(
      `refusing to apply: ${plan.collisions.length} collision(s) — ${plan.collisions
        .map(({ from, to }) => `${from} → ${to}`)
        .join(", ")}. Resolve them by hand, then re-run \`ocean layout plan\`.`,
    );

  // 1. Snapshot every pointer before anything changes.
  const startedAt = new Date().toISOString();
  const backup = path.join(home, BACKUPS, startedAt.replace(/[:.]/g, "-"));
  await mkdir(path.join(backup, "pointers"), { recursive: true, mode: 0o700 });
  await chmod(path.join(home, BACKUPS), 0o700);
  const moves = plan.moves.map(({ from, to }) => ({ from, to }));
  const pointers: PointerBackup[] = [];
  for (const [index, pointer] of plan.pointers.entries()) {
    if (pointer.kind === "symlink") {
      pointers.push({ ...pointer, backup: await readlink(pointer.file) });
      continue;
    }
    const name = `${index}-${path.basename(pointer.file)}`;
    await copyFile(pointer.file, path.join(backup, "pointers", name));
    pointers.push({ file: pointer.file, kind: "file", backup: name });
  }
  const gitignorePath = path.join(root, ".gitignore");
  const hasGitignore =
    plan.gitignore.length > 0 && (await exists(gitignorePath));
  if (hasGitignore)
    await copyFile(gitignorePath, path.join(backup, "gitignore"));
  const journal: LayoutJournal = {
    version: 1,
    root,
    home,
    startedAt,
    step: "snapshotted",
    moves,
    pointers,
    gitignore: hasGitignore ? "gitignore" : null,
    manifests: {},
  };
  await writeJournal(backup, journal);

  // 2. Copy into staging and prove the copy byte-for-byte before it becomes visible.
  await mkdir(staging);
  for (const { from, to } of moves) {
    const source = path.join(root, from);
    const staged = path.join(staging, to);
    await cp(source, staged, {
      recursive: true,
      errorOnExist: true,
      force: false,
      preserveTimestamps: true,
      verbatimSymlinks: true,
    });
    const changed = differences(await manifest(source), await manifest(staged));
    if (changed.length)
      throw new Error(
        `copy of ${from} does not match its source (${changed.slice(0, 5).join(", ")}${changed.length > 5 ? ", …" : ""}); was it written during the copy? Nothing is live yet — run \`ocean layout rollback\`.`,
      );
  }
  journal.step = "copied";
  await writeJournal(backup, journal);

  // 3. Rename into place, the records' sentinel last.
  const ordered = [...moves].sort(
    (a, b) => Number(a.to === LAST) - Number(b.to === LAST),
  );
  for (const { to } of ordered)
    await rename(path.join(staging, to), path.join(root, to));
  await rm(staging, { recursive: true });
  journal.step = "swapped";
  await writeJournal(backup, journal);

  // 4. Repoint: files outside the root in place, files inside an old tree in their new copy.
  let repointed = 0;
  for (const pointer of pointers) {
    const target = newLocation(pointer.file, root, moves);
    if (pointer.kind === "symlink")
      await replaceLink(target, repoint(pointer.backup, root, home));
    else
      await writeAtomic(
        target,
        repoint(await readFile(target, "utf8"), root, home),
      );
    repointed += 1;
  }
  if (hasGitignore)
    await writeAtomic(
      gitignorePath,
      applyGitignore(await readFile(gitignorePath, "utf8"), plan),
    );

  for (const { to } of moves)
    journal.manifests[to] = await manifest(path.join(root, to));
  journal.step = "done";
  await writeJournal(backup, journal);
  return {
    applied: true,
    reason: "new layout in place; the old trees are untouched",
    backup,
    moved: moves.map(({ from, to }) => `${from} → ${to}`),
    repointed,
  };
}

async function latestJournal(
  home: string,
  root: string,
): Promise<{ backup: string; journal: LayoutJournal } | null> {
  const folder = path.join(home, BACKUPS);
  const names = (await readdir(folder).catch(() => [])).sort().reverse();
  for (const name of names) {
    const backup = path.join(folder, name);
    const journal = JSON.parse(
      await readFile(path.join(backup, "journal.json"), "utf8").catch(
        () => "null",
      ),
    ) as LayoutJournal | null;
    if (journal?.root === root && journal.step !== "rolled-back")
      return { backup, journal };
  }
  return null;
}

export type RollbackResult = {
  rolledBack: boolean;
  reason: string;
  backup?: string;
  removed?: string[];
  restored?: number;
};

export async function rollbackLayout(
  root: string,
  home: string = os.homedir(),
): Promise<RollbackResult> {
  const found = await latestJournal(home, root);
  const staging = path.join(root, STAGING);
  if (!found) {
    if (await exists(staging))
      throw new Error(
        `${staging} exists but no journal under ${path.join(home, BACKUPS)} names this root; remove it by hand after checking it.`,
      );
    return { rolledBack: false, reason: "no apply to roll back" };
  }
  const { backup, journal } = found;
  const { moves } = journal;
  const placed = [];
  for (const move of moves)
    if (await exists(path.join(root, move.to))) placed.push(move);

  // Check everything before touching anything: the old trees must still be there, and a new tree
  // may only go if it is exactly what apply left — a write since then would otherwise be lost.
  for (const { from } of moves)
    if (!(await exists(path.join(root, from))))
      throw new Error(
        `refusing to roll back: ${from} is gone, so the new copy is the only one left.`,
      );
  if (journal.step === "done") {
    for (const { to } of placed) {
      const changed = differences(
        journal.manifests[to] ?? {},
        await manifest(path.join(root, to)),
      );
      if (changed.length)
        throw new Error(
          `refusing to roll back: ${to} changed since apply (${changed.slice(0, 5).join(", ")}${changed.length > 5 ? ", …" : ""}). Move those changes to the old tree first.`,
        );
    }
  } else if (journal.step === "swapped") {
    // Interrupted while repointing: the new trees may hold rewritten pointers, nothing else.
  } else if (placed.length) {
    // Interrupted mid-rename: a placed tree is still byte-identical to its source.
    for (const { from, to } of placed) {
      const changed = differences(
        await manifest(path.join(root, from)),
        await manifest(path.join(root, to)),
      );
      if (changed.length)
        throw new Error(
          `refusing to roll back: ${to} differs from ${from} (${changed.slice(0, 5).join(", ")}).`,
        );
    }
  }

  let restored = 0;
  for (const pointer of journal.pointers) {
    if (insideOldTree(pointer.file, root, moves)) continue;
    if (pointer.kind === "symlink")
      await replaceLink(pointer.file, pointer.backup);
    else
      await writeAtomic(
        pointer.file,
        await readFile(path.join(backup, "pointers", pointer.backup), "utf8"),
      );
    restored += 1;
  }
  if (journal.gitignore)
    await writeAtomic(
      path.join(root, ".gitignore"),
      await readFile(path.join(backup, journal.gitignore), "utf8"),
    );
  await rm(staging, { recursive: true, force: true });
  for (const { to } of placed)
    await rm(path.join(root, to), { recursive: true });
  journal.step = "rolled-back";
  await writeJournal(backup, journal);
  return {
    rolledBack: true,
    reason:
      "pointers restored; the new copies removed; the old trees were never touched",
    backup,
    removed: placed.map(({ to }) => to),
    restored,
  };
}
