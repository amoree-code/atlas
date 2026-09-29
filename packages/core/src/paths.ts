import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));

// This module always lives one directory below the engine package root, whether it
// runs compiled from dist/ or directly from src/ under tsx.
const engineDirectory = path.resolve(moduleDirectory, "..");

// The default runtime data root is the private workspace root, e.g.
// ~/ocean/kernel/packages/core (this package) sits three directories below ~/ocean
// (kernel, packages, core), which itself sits next to ~/ocean/brain and
// ~/ocean/kernel/bridge (see PERSONAL_DIR/PROJECTS_DIR/SYSTEM_DIR below).
const defaultAtlasRoot = path.resolve(engineDirectory, "..", "..", "..");

export function engineRoot(): string {
  return engineDirectory;
}

export function enginePath(...parts: string[]): string {
  return path.join(engineRoot(), ...parts);
}

// The pnpm workspace root (engine/), two directories above this package
// (packages/core → packages → engine). Repo-wide tooling that lives outside any
// workspace package (e.g. scripts/ shared across packages) is anchored here, not on
// engineRoot(), which is this package's own root.
export function repoRoot(): string {
  return path.resolve(engineDirectory, "..", "..");
}

export function repoPath(...parts: string[]): string {
  return path.join(repoRoot(), ...parts);
}

// Single point of truth for the top-level layout under atlasRoot(). Flipped in
// T-224 stage B to the Ocean/PARA layout (~/ocean/brain/..., ~/ocean/kernel/bridge)
// now that every call site (stage A) reads these constants instead of a literal.
export const PERSONAL_DIR = "brain/02-personal";
export const PROJECTS_DIR = "brain/04-projects";
export const SYSTEM_DIR = "kernel/bridge";

export function atlasRoot(): string {
  return process.env.ATLAS_ROOT
    ? path.resolve(process.env.ATLAS_ROOT)
    : defaultAtlasRoot;
}

export function atlasPath(...parts: string[]): string {
  return path.join(atlasRoot(), ...parts);
}

// path.resolve is purely lexical: it never follows symlinks. Resolves the real location
// of the deepest existing ancestor of `candidate` and rejoins the (possibly not-yet-created)
// remainder onto it, so a caller can bounds-check a write target that doesn't exist yet
// without requiring the whole path to exist first.
function realDeepestExisting(candidate: string): string {
  let current = candidate;
  const pendingSuffix: string[] = [];
  for (;;) {
    try {
      return path.join(realpathSync(current), ...pendingSuffix.reverse());
    } catch {
      const parent = path.dirname(current);
      if (parent === current) return candidate;
      pendingSuffix.push(path.basename(current));
      current = parent;
    }
  }
}

function escapesRoot(root: string, candidate: string): boolean {
  const isFilesystemRoot = root === path.parse(root).root;
  return (
    candidate !== root &&
    !isFilesystemRoot &&
    !candidate.startsWith(`${root}${path.sep}`)
  );
}

export function resolveWithin(root: string, ...parts: string[]): string {
  const resolvedRoot = path.resolve(root);
  const resolved = path.resolve(resolvedRoot, ...parts);
  if (escapesRoot(resolvedRoot, resolved)) {
    throw new Error("Path escapes its allowed root");
  }
  // A symlink anywhere under the lexically-allowed path can still point outside root; the
  // lexical check above can't see that. Re-check against each path's real location too.
  const realRoot = realDeepestExisting(resolvedRoot);
  const realResolved = realDeepestExisting(resolved);
  if (escapesRoot(realRoot, realResolved)) {
    throw new Error("Path escapes its allowed root");
  }
  return resolved;
}
