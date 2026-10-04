import {
  cp,
  lstat,
  mkdir,
  readdir,
  readlink,
  rename,
  stat,
  symlink,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { atlasPath, enginePath, SYSTEM_DIR } from "../../paths.js";
import { clientSkillRoots, type SkillClient } from "./core-skill-sync.js";

// The hub is the one place skills live inside Ocean. Clients hold symlinks into it, so
// there is a single copy to edit and nothing drifts per client.
export function skillHubRoot(): string {
  return atlasPath(SYSTEM_DIR, "skills");
}

async function skillDirectories(root: string): Promise<string[]> {
  const names: string[] = [];
  for (const entry of await readdir(root, { withFileTypes: true })) {
    // Follow symlinks: a client may expose another store's skills as links.
    const full = path.join(root, entry.name);
    const isDirectory = entry.isDirectory() || (await stat(full)).isDirectory();
    if (!isDirectory) continue;
    try {
      await stat(path.join(full, "SKILL.md"));
      names.push(entry.name);
    } catch {
      /* not a skill directory */
    }
  }
  return names.sort();
}

// Additive: copies the engine's core skills and any extra source folders into the hub.
// An existing hub skill is never overwritten.
export async function populateSkillHub(
  extraSources: string[] = [],
): Promise<{ added: string[]; kept: string[] }> {
  const hub = skillHubRoot();
  await mkdir(hub, { recursive: true });
  const added: string[] = [];
  const kept: string[] = [];
  for (const source of [enginePath("skills", "core"), ...extraSources]) {
    for (const name of await skillDirectories(source)) {
      const target = path.join(hub, name);
      try {
        await lstat(target);
        kept.push(name);
      } catch {
        await cp(path.join(source, name), target, {
          recursive: true,
          dereference: true,
        });
        added.push(name);
      }
    }
  }
  return { added, kept };
}

export type LinkAction = {
  client: SkillClient;
  skill: string;
  action: "linked" | "create" | "replace" | "skip";
};

// Dry run unless `apply`. Skills a client does not already have are only added with `all`:
// every extra skill costs that client always-on context. A real directory (or a link elsewhere) already at the target is
// moved into a timestamped backup under the bridge archive before the link is made.
export async function linkClientSkills(options: {
  apply?: boolean;
  all?: boolean;
  home?: string;
  hub?: string;
}): Promise<{ actions: LinkAction[]; backup: string | null }> {
  const home = options.home ?? os.homedir();
  const hub = options.hub ?? skillHubRoot();
  const backup = path.join(
    atlasPath(SYSTEM_DIR, "archive"),
    `skills-backup-${new Date().toISOString().replace(/[:.]/g, "-")}`,
  );
  const actions: LinkAction[] = [];
  let backedUp = false;
  const names = await skillDirectories(hub);
  for (const client of Object.keys(clientSkillRoots) as SkillClient[]) {
    const root = clientSkillRoots[client](home);
    try {
      await stat(root);
    } catch {
      continue; // client not installed
    }
    for (const skill of names) {
      const target = path.join(root, skill);
      const wanted = path.join(hub, skill);
      let action: LinkAction["action"] = "create";
      try {
        const info = await lstat(target);
        if (
          info.isSymbolicLink() &&
          path.resolve(root, await readlink(target)) === wanted
        ) {
          action = "linked";
        } else {
          action = "replace";
        }
      } catch {
        /* absent */
      }
      if (action === "create" && !options.all) action = "skip";
      actions.push({ client, skill, action });
      if (!options.apply || action === "linked" || action === "skip") continue;
      if (action === "replace") {
        const saved = path.join(backup, client);
        await mkdir(saved, { recursive: true });
        await rename(target, path.join(saved, skill));
        backedUp = true;
      }
      await symlink(wanted, target, "dir");
    }
  }
  return { actions, backup: backedUp ? backup : null };
}
