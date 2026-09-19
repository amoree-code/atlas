import type { ProjectResolution } from "./project-resolution.js";

// This module used to read Atlas files (memory, knowledge, inbox, README, governance rules)
// and inject their full content into every provider launch. That bulk injection is removed
// per T-198: providers get a tiny identity/bootstrap signal only, never Atlas file contents.
// On-demand reads happen through explicit Atlas operations (tickets, memory, knowledge, …),
// not through what gets stuffed into a launch argument or env var at startup.
export const ATLAS_BOOTSTRAP_MAX_BYTES = 256;

export type AtlasBootstrap = {
  content: string;
  manifest: { bytes: number; source: "atlas"; transport: "bootstrap-env" };
};

const SUPPORTED_OPERATIONS = "context,tickets,memory-search,knowledge-search";

function projectTag(project: ProjectResolution): string {
  if (project.status === "bound") return project.projectId;
  return project.status;
}

// Bounded, client-neutral: identifies Atlas as canonical and the resolved project (or its
// absence), and names the on-demand operations a client can call. Never Atlas file content.
export function buildAtlasBootstrap(
  project: ProjectResolution,
): AtlasBootstrap {
  const content = `atlas=1 project=${projectTag(project)} confidence=${project.confidence} ops=${SUPPORTED_OPERATIONS}`;
  const bytes = Buffer.byteLength(content, "utf8");
  if (bytes > ATLAS_BOOTSTRAP_MAX_BYTES) {
    throw new Error(
      `Atlas bootstrap exceeds the ${ATLAS_BOOTSTRAP_MAX_BYTES}-byte budget (${bytes} bytes): ${content}`,
    );
  }
  return {
    content,
    manifest: { bytes, source: "atlas", transport: "bootstrap-env" },
  };
}

// Delivered as environment variables only — never written into provider argv or a
// provider-owned context file, and never a second source of truth for provider memory.
export function bootstrapEnvironment(
  bootstrap: AtlasBootstrap,
): Record<string, string> {
  return {
    ATLAS_BOOTSTRAP: bootstrap.content,
    ATLAS_BOOTSTRAP_BYTES: String(bootstrap.manifest.bytes),
  };
}
