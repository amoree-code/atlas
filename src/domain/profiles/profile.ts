import { createHash } from "node:crypto";
import { z } from "zod";

export const profileSchema = z.object({
  name: z.string().min(1),
  description: z.string().default(""),
  version: z.string().min(1).default("1.0.0"),
  provider: z.enum(["claude", "codex", "gemini", "antigravity"]),
  model: z.string().min(1),
  role: z.string().min(1),
  skills: z.array(z.string()).default([]),
  allowedPaths: z.array(z.string()).default([]),
  allowedCommands: z.array(z.string()).default([]),
  writePolicy: z.enum(["none", "workspace", "allowed-paths"]).default("none"),
  contextSources: z.array(z.string()).default([]),
});

export type Profile = z.infer<typeof profileSchema>;

// A deterministic identity for the exact configuration a profile had at the moment a
// session was created from it: same fields (including `version`) always hash to the same
// value, so a session can be traced back to the profile shape that produced it even after
// the profile file on disk is later edited. Key order is fixed explicitly rather than
// relying on object insertion order, since callers may construct a Profile in any order.
export function profileIdentity(profile: Profile): string {
  const canonical = {
    name: profile.name,
    description: profile.description,
    version: profile.version,
    provider: profile.provider,
    model: profile.model,
    role: profile.role,
    skills: profile.skills,
    allowedPaths: profile.allowedPaths,
    allowedCommands: profile.allowedCommands,
    writePolicy: profile.writePolicy,
    contextSources: profile.contextSources,
  };
  return createHash("sha256").update(JSON.stringify(canonical)).digest("hex");
}
