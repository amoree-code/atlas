// Composition root. This is the one place (besides entry points) allowed to
// import infrastructure concretes: it wires them to the domain ports that the
// application layer depends on. Dependencies point inward everywhere else —
// application → domain ports, never application → infrastructure.

import type { AuthDeps } from "../application/auth/auth-orchestrator.js";
import type {
  ProviderRegistryPort,
  WrapperManagerPort,
} from "../domain/ports/platform-ports.js";
import type { AgentRuntimeDeps } from "../domain/ports/runtime-ports.js";
import type { SessionStoreFactory } from "../domain/ports/session-store-port.js";
import { loadProfile } from "../infrastructure/filesystem/profile-loader.js";
import { loadSkillIndex } from "../infrastructure/filesystem/skill-loader.js";
import { appendRuntimeLog } from "../infrastructure/observability/runtime-logger.js";
import { openSessionStore } from "../infrastructure/persistence/session-store.js";
import { runHeadless } from "../infrastructure/process/cli-process.js";
import { runInteractive } from "../infrastructure/process/interactive-process.js";
import { resolveClientHome } from "../infrastructure/providers/client-home.js";
import { resolveOriginalExecutable } from "../infrastructure/providers/provider-registry.js";
import {
  assertProviderSupportsReadOnly,
  runProvider,
} from "../infrastructure/providers/providers.js";
import {
  desktopWrapperPath,
  registerProvider,
  removeProvider,
  syncProviderWrappers,
  wrapperDoctor,
} from "../infrastructure/wrappers/wrapper-manager.js";

/** The concrete session-store factory, as the SessionStoreFactory port. */
export const defaultSessionStoreFactory: SessionStoreFactory = openSessionStore;

/** The concrete dependency set for `runAgent`/`resumeAgent`. */
export const defaultAgentRuntime: AgentRuntimeDeps = {
  openStore: openSessionStore,
  executeProvider: runProvider,
  loadProfile,
  loadSkillIndex,
  resolveClientHome,
  appendRuntimeLog,
  assertProviderSupportsReadOnly,
};

/**
 * Build an agent runtime with the real implementations, overriding any subset —
 * used by tests to inject a fake provider executor while keeping the rest real.
 */
export function createAgentRuntime(
  overrides: Partial<AgentRuntimeDeps> = {},
): AgentRuntimeDeps {
  return { ...defaultAgentRuntime, ...overrides };
}

/** Shell wrapper management, as the WrapperManagerPort. */
export const defaultWrapperManager: WrapperManagerPort = {
  syncProviderWrappers,
  registerProvider,
  removeProvider,
  wrapperDoctor,
  desktopWrapperPath,
};

/** The provider registry, as the ProviderRegistryPort. */
export const defaultProviderRegistry: ProviderRegistryPort = {
  resolveOriginalExecutable,
};

/** Dependencies for the auth flows. */
export const defaultAuthDeps: AuthDeps = {
  registry: defaultProviderRegistry,
  runHeadless,
  runInteractive,
};
