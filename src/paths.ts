import { realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));

// This module always lives one directory below the engine package root, whether it
// runs compiled from dist/ or directly from src/ under tsx.
const engineDirectory = path.resolve(moduleDirectory, "..");

// The default runtime data root is the private workspace sibling of engine/, e.g.
// ~/atlas/engine (this package) next to ~/atlas/personal, ~/atlas/projects, and ~/atlas/system.
const defaultAtlasRoot = path.resolve(engineDirectory, "..");

export function engineRoot(): string {
  return engineDirectory;
}

export function enginePath(...parts: string[]): string {
  return path.join(engineRoot(), ...parts);
}

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

// Private application state (config, profiles, sessions, logs, and integrations)
// lives at the workspace root, separate from the public engine and user data trees.
export function atlasStatePath(...parts: string[]): string {
  return atlasPath(...parts);
}
