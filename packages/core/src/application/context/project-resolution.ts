import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { registryFile } from "../../fs-utils.js";
import { oceanRoot, WORKSPACE_PROJECT_ID } from "../../paths.js";

// Deterministic, local, metadata-first project resolution: no model call, no network round
// trip. Bindings are a flat JSON registry (same pattern as kernel/bridge/registry/
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
      matchedOn: "git-root" | "cwd" | "path" | "ocean-root";
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
    return "Which Ocean project should this request use? Specify the project name or binding path.";
  return "Which Ocean project should this request use? Provide the project name and path to bind it.";
}

function bindingsFile(): string {
  return registryFile("project-bindings.json");
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

const execFileAsync = promisify(execFile);

// `git status --short` lines for the repo containing `directory`; [] when it is not a repo or
// git fails. --no-optional-locks: sessions share working trees, and a status that refreshes the
// index would take index.lock and fail another session's concurrent add/commit (T-257).
export async function gitChangedFiles(
  directory: string,
  timeout = 1_000,
): Promise<string[]> {
  try {
    const { stdout } = await execFileAsync(
      "git",
      ["--no-optional-locks", "-C", directory, "status", "--short"],
      { timeout, maxBuffer: 1024 * 1024 },
    );
    return stdout
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
  } catch {
    return [];
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
  const tmp = `${file}.ocean-tmp-${process.pid}`;
  await writeFile(
    tmp,
    `${JSON.stringify({ version: 1, bindings }, null, 2)}\n`,
    "utf8",
  );
  await rename(tmp, file);
}

// Resolves the active Ocean project from a working directory: no terminal-in-Ocean
// requirement. Match order is git root, then the exact cwd, then (as a last resort) whether
// the path is inside the Ocean workspace root itself, which is always the workspace project.
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

  const root = oceanRoot();
  const isFilesystemRoot = root === path.parse(root).root;
  if (
    resolvedCwd === root ||
    isFilesystemRoot ||
    resolvedCwd.startsWith(`${root}${path.sep}`)
  ) {
    return {
      status: "bound",
      projectId: WORKSPACE_PROJECT_ID,
      name: "Ocean",
      path: root,
      matchedOn: "ocean-root",
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
