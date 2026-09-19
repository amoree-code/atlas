import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath, atlasRoot } from "../../paths.js";

// Deterministic, local, metadata-first project resolution: no model call, no network round
// trip. Bindings are a flat JSON registry (same pattern as system/control-plane/registry/
// providers.json), not a new workspace root.
export type ProjectBinding = {
  id: string;
  name: string;
  path: string;
  gitRoot: string | null;
  boundAt: string;
};

export type ProjectResolution =
  | {
      status: "bound";
      projectId: string;
      name: string;
      path: string;
      matchedOn: "git-root" | "cwd" | "path" | "atlas-root";
      confidence: "high";
    }
  | {
      status: "unbound";
      cwd: string;
      gitRoot: string | null;
      confidence: "none";
    }
  | {
      status: "ambiguous";
      cwd: string;
      candidates: ProjectBinding[];
      confidence: "low";
    };

export function projectConfirmationQuestion(
  resolution: ProjectResolution,
): string | null {
  if (resolution.status === "bound") return null;
  if (resolution.status === "ambiguous")
    return "Which Atlas project should this request use? Specify the project name or binding path.";
  return "Which Atlas project should this request use? Provide the project name and path to bind it.";
}

function bindingsFile(): string {
  return atlasPath(
    "system",
    "control-plane",
    "registry",
    "project-bindings.json",
  );
}

export function findGitRoot(startDir: string): string | null {
  let dir = path.resolve(startDir);
  while (true) {
    if (existsSync(path.join(dir, ".git"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

export async function listProjectBindings(): Promise<ProjectBinding[]> {
  try {
    const raw = await readFile(bindingsFile(), "utf8");
    const parsed = JSON.parse(raw) as {
      version: number;
      bindings: ProjectBinding[];
    };
    return parsed.bindings ?? [];
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw error;
  }
}

async function saveProjectBindings(bindings: ProjectBinding[]): Promise<void> {
  const file = bindingsFile();
  await mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.atlas-tmp-${process.pid}`;
  await writeFile(
    tmp,
    `${JSON.stringify({ version: 1, bindings }, null, 2)}\n`,
    "utf8",
  );
  await rename(tmp, file);
}

// Resolves the active Atlas project from a working directory: no terminal-in-Atlas
// requirement. Match order is git root, then the exact cwd, then (as a last resort) whether
// the path is inside the Atlas workspace root itself, which is always project "atlas".
export async function resolveProject(cwd: string): Promise<ProjectResolution> {
  const resolvedCwd = path.resolve(cwd);
  const gitRoot = findGitRoot(resolvedCwd);
  const bindings = await listProjectBindings();

  const containing = bindings
    .filter((binding) => {
      const bound = path.resolve(binding.path);
      return (
        resolvedCwd === bound || resolvedCwd.startsWith(`${bound}${path.sep}`)
      );
    })
    .sort((a, b) => path.resolve(b.path).length - path.resolve(a.path).length);
  if (
    containing.length &&
    (!containing[1] ||
      path.resolve(containing[0].path).length >
        path.resolve(containing[1].path).length)
  ) {
    const binding = containing[0];
    return {
      status: "bound",
      projectId: binding.id,
      name: binding.name,
      path: binding.path,
      matchedOn: path.resolve(binding.path) === resolvedCwd ? "cwd" : "path",
      confidence: "high",
    };
  }
  if (containing.length > 1)
    return {
      status: "ambiguous",
      cwd: resolvedCwd,
      candidates: containing,
      confidence: "low",
    };

  const gitRootMatch = gitRoot
    ? bindings.filter((binding) => path.resolve(binding.path) === gitRoot)
    : [];
  if (gitRootMatch.length === 1) {
    return {
      status: "bound",
      projectId: gitRootMatch[0].id,
      name: gitRootMatch[0].name,
      path: gitRootMatch[0].path,
      matchedOn: "git-root",
      confidence: "high",
    };
  }
  if (gitRootMatch.length > 1) {
    return {
      status: "ambiguous",
      cwd: resolvedCwd,
      candidates: gitRootMatch,
      confidence: "low",
    };
  }

  const root = atlasRoot();
  const isFilesystemRoot = root === path.parse(root).root;
  if (
    resolvedCwd === root ||
    isFilesystemRoot ||
    resolvedCwd.startsWith(`${root}${path.sep}`)
  ) {
    return {
      status: "bound",
      projectId: "atlas",
      name: "Atlas",
      path: root,
      matchedOn: "atlas-root",
      confidence: "high",
    };
  }

  return { status: "unbound", cwd: resolvedCwd, gitRoot, confidence: "none" };
}

export type BindProjectResult = {
  binding: ProjectBinding;
  created: boolean;
  conflict?: ProjectBinding;
};

// Explicit registration/binding: never guesses on a name or path collision, always returns
// the conflict instead of silently overwriting an existing binding.
export async function bindProject(
  name: string,
  targetPath: string,
): Promise<BindProjectResult> {
  const resolvedPath = path.resolve(targetPath);
  const bindings = await listProjectBindings();

  const existingAtPath = bindings.find(
    (binding) => path.resolve(binding.path) === resolvedPath,
  );
  if (existingAtPath) {
    if (existingAtPath.name === name)
      return { binding: existingAtPath, created: false };
    return {
      binding: existingAtPath,
      created: false,
      conflict: existingAtPath,
    };
  }

  const existingByName = bindings.find((binding) => binding.name === name);
  if (existingByName)
    return {
      binding: existingByName,
      created: false,
      conflict: existingByName,
    };

  const binding: ProjectBinding = {
    id: name,
    name,
    path: resolvedPath,
    gitRoot: findGitRoot(resolvedPath),
    boundAt: new Date().toISOString(),
  };
  await saveProjectBindings([...bindings, binding]);
  return { binding, created: true };
}
