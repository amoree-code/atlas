---
name: workspace-health
description: Check the AI OS workspace for missing files, broken config, stale tasks, drifted registry, and security problems. Use when the user says health check, check my setup, is everything ok, or audit the workspace.
---

# Workspace health

Read-only. Diagnose; never fix without being asked.

## Steps

1. ```bash
   ~/.ai-os/config/scripts/health-check.sh
   ```
   Covers structure, client config (if applicable), skill validity, script syntax,
   today's folder, global gitignore, SSH perms, and credential patterns.

2. **Memory and knowledge health:**
   ```bash
   ai-os-doctor
   ```
   Covers the mechanical checks: the required sections present, frontmatter present on
   every file, duplicate `name:` slugs, near-identical descriptions (possible duplicate
   memories), broken `[[wiki-links]]`, files missing from `MEMORY.md`, entries marked
   `outdated`/`temporary`, and unresolved items in `CONFLICTS.md`.

   Then judge what a script cannot:
   - **Misclassified** — a fact in the wrong section. Apply the test: *would this still
     be true if the user never wrote another line of code?* Yes → `memory/`, no →
     `knowledge/`. Country/company/one-off facts belong inside an existing section by
     meaning, never their own top-level section.
   - **Duplicated across sections** — the same fact stated in two places rather than one
     canonical home plus a link. Say which copy should be canonical.
   - **Outdated** — a `last_verified` older than ~6 months on something that changes
     (job title, current status, priorities), or a goal already achieved.
   - **Knowledge quality** — a `knowledge/` entry that is long, narrative, or
     transcript-like has failed its purpose. Flag it for compression.

3. **Registry drift** — a script can't judge this:
   ```bash
   find ~/Documents -maxdepth 6 -type d -name .git -not -path "*/node_modules/*" | sed 's|/.git$||'
   ```
   Compare against `~/.ai-os/projects/registry.md`. Report repos missing from it, and
   registry rows whose path no longer exists.

4. **Stale tasks** — flag any `TODO`/`WIP` in `projects/tasks.md` whose `{created}` is
   more than 30 days old, and any `BLOCKED` with no note on what it's waiting for.

5. **Session hygiene** — if the newest session record is over 14 days old while repos have
   uncommitted work, the continuity loop isn't being used. Say so.

## Report

Group as **FAIL** (broken, fix now) · **WARN** (drifted, fix soon) · **OK** (one line
total). For each FAIL give the one command or edit that fixes it. Then ask before fixing
anything.

Never print secret values — report the file and line only.
