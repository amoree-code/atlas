import path from "node:path";
import type { Profile } from "../../domain/profiles/profile.js";
import { atlasPath } from "../../paths.js";

export function resolveClientHome(profile: Profile): string | undefined {
  const configured = profile.clients[profile.provider]?.home;
  if (!configured) return undefined;
  const root = path.resolve(atlasPath("system", "clients"));
  const resolved = path.resolve(atlasPath(configured));
  if (resolved !== root && !resolved.startsWith(`${root}${path.sep}`)) {
    throw new Error(
      `Client home must stay under Atlas system/clients: ${configured}`,
    );
  }
  return resolved;
}
