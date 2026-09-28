import type { ContextManifest } from "../context/context.js";
import type { HeadlessResult } from "../process/process-events.js";
import type { Profile } from "../profiles/profile.js";
import type {
  HeadlessProvider,
  ProviderRequest,
} from "../providers/provider.js";
import type { Skill } from "../skills/skill.js";
import type { SessionStoreFactory } from "./session-store-port.js";

// Function ports the application depends on. The composition root binds these to
// their infrastructure implementations; application code never imports the
// concretes.

export type ProviderExecutor = (
  request: ProviderRequest,
) => Promise<HeadlessResult>;

export type ProfileLoader = (name: string) => Promise<Profile>;

export type BuiltContext = { manifest: ContextManifest; content: string };
export type ContextBuilder = (
  profile: Profile,
  root: string,
  maxBytes?: number,
  options?: { compression?: "none" | "atlas-bounded" },
) => Promise<BuiltContext>;

export type SkillLoader = (
  names: string[],
  maxBytes?: number,
  cwd?: string,
) => Promise<Skill[]>;

export type ClientHomeResolver = (profile: Profile) => string | undefined;

export type RuntimeLogEntry = {
  timestamp: string;
  event: string;
  correlationId: string;
  provider?: string;
  sessionId?: string;
  status?: string;
  payload?: string;
};
export type RuntimeLogger = (log: RuntimeLogEntry) => Promise<void>;

export type ReadOnlyAssertion = (provider: HeadlessProvider) => void;

/**
 * The full set of infrastructure dependencies `runAgent`/`resumeAgent` need.
 * The composition root supplies concrete implementations; the run functions
 * import only this type from the domain layer.
 */
export type AgentRuntimeDeps = {
  openStore: SessionStoreFactory;
  executeProvider: ProviderExecutor;
  loadProfile: ProfileLoader;
  buildContext: ContextBuilder;
  loadSkills: SkillLoader;
  resolveClientHome: ClientHomeResolver;
  appendRuntimeLog: RuntimeLogger;
  assertProviderSupportsReadOnly: ReadOnlyAssertion;
};
