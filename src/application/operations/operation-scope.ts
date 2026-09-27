import { atlasPath } from "../../paths.js";
import { resolveProject } from "../context/project-resolution.js";
import type { OperationRecord, WriteApproval } from "./operation-contract.js";

export type OperationOptions = {
  cwd?: string;
  approval?: WriteApproval;
  requestedProject?: string;
  patch?: Record<string, string>;
  content?: string;
  slug?: string;
  kind?: string;
  query?: string;
  projectPath?: string;
  provenance?: OperationRecord["provenance"];
  correctionOf?: string;
};

export type ProjectScope =
  | { ok: true; projectId: string }
  | { ok: false; reason: string };

async function activeProjectId(cwd: string): Promise<ProjectScope> {
  const resolution = await resolveProject(cwd);
  if (resolution.status === "bound")
    return { ok: true, projectId: resolution.projectId };
  return {
    ok: false,
    reason: `no bound Atlas project for this working directory (status: ${resolution.status})`,
  };
}

export function taskRoot(projectId: string): string {
  return atlasPath("projects", projectId, "tasks");
}

export async function crossProjectGuard(
  options: OperationOptions,
  cwd: string,
): Promise<ProjectScope> {
  const active = await activeProjectId(cwd);
  if (!active.ok) return active;
  if (
    options.requestedProject &&
    options.requestedProject !== active.projectId
  ) {
    return {
      ok: false,
      reason: `cross-project request refused: active project is '${active.projectId}', request targeted '${options.requestedProject}'`,
    };
  }
  return active;
}
