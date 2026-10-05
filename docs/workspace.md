# Workspace

Atlas separates the public **engine** (`kernel/` in this repository) from a private
**workspace** (`~/ocean`) that holds every piece of user and runtime data. `kernel/` is
`~/ocean`'s own git repository with its own remote — the workspace root above it is a
separate, private, no-remote repository (see `git.md`'s policy for the boundary).
`kernel/bridge/` is machine-local state physically nested inside this repository but
git-ignored here; `brain/` is user-owned data that lives entirely outside this repository.

## Layout

```text
<workspace root>/           default: the parent directory of kernel/ (e.g. ~/ocean)
├── brain/                   user-owned private data (PARA)
│   ├── 00-inbox/ … 06-templates/, 99-archive/
│   └── 04-projects/         project data (registry, backlog, per-project tasks)
├── kernel/                   this repository
│   └── bridge/               machine-local state, git-ignored
│       ├── profiles/         one JSON file per profile (see profiles.md)
│       ├── sessions/
│       │   └── sessions.sqlite   session store (see sessions.md)
│       ├── config/
│       │   ├── startup/
│       │   └── CONFIG.md
│       ├── control-plane/    private governance and permissions
│       ├── integrations/     private client integrations
│       └── archive/          private retained legacy history
```

## Root resolution (`src/paths.ts`)

- `engineRoot()` / `enginePath(...)` — always the directory containing this package
  (resolved from the running module, whether compiled under `dist/` or run under `tsx`
  from `src/`).
- `atlasRoot()` — `process.env.ATLAS_ROOT` if set (resolved to an absolute path),
  otherwise the parent directory of `engineRoot()`. This is the default private-workspace
  location: `kernel/` is expected to sit inside the workspace root as a sibling of `brain/`.
- `atlasPath(...)` — joins onto `<atlasRoot>/`, used for all private workspace state, via
  the `PERSONAL_DIR`/`PROJECTS_DIR`/`SYSTEM_DIR` constants (currently `brain/02-personal`,
  `brain/04-projects`, `kernel/bridge`).

Set `ATLAS_ROOT` to point Atlas at a different workspace root, for example to run multiple
isolated workspaces from one engine checkout.

## Bootstrap (`atlas setup`)

`src/interfaces/cli/setup-command.ts` creates the workspace on first run (paths below via
the same three constants, so they track any future layout change):

- Creates `brain/02-personal`, `brain/05-knowledge`, `brain/01-daily`, `brain/00-inbox`,
  `brain/06-templates`, and `brain/04-projects/atlas/tasks`
  under the workspace root.
- Creates `kernel/bridge/config/startup`, `kernel/bridge/profiles`,
  `kernel/bridge/sessions`, `kernel/bridge/control-plane`, `kernel/bridge/integrations`, and
  `kernel/bridge/archive` under the workspace root.
- Writes `kernel/bridge/profiles/default.json` from the template in `packages/core/templates/`,
  without overwriting existing files.
- Installs a per-OS startup entry that launches `kernel/packages/core/dist/main.js service`
  with the workspace root as its working directory: a macOS `launchd` plist under
  `~/Library/LaunchAgents`, a Linux `systemd --user` unit under
  `~/.config/systemd/user`, or a Windows Startup-folder launcher script.
- Restricts the private `kernel/bridge` tree to `0700` permissions.

Startup always points at `kernel/packages/core/dist/main.js` (the built engine), never at
`src/`, and always runs with the private workspace directory as its current working
directory.

## Task completion and archive

Use the governed completion command when a task is genuinely finished:

```bash
atlas tasks complete T-123
```

It requires every checklist item to be checked, writes `state: done`, and moves the
whole task directory (including sibling artifacts) into `projects/atlas/tasks/archive/`
in one operation. Read-only commands such as `atlas tasks list` do not mutate files.

Tasks that were marked `done` by an external editor can be reconciled explicitly:

```bash
atlas tasks archive --auto
```

There is no background filesystem watcher; this keeps completion deterministic and avoids
making a read-only inspection command silently move user data.

## Skills

There is one live skills store: `bridge/skills` (machine-local, git-ignored). AI clients hold symlinks
into it instead of their own copies. `packages/core/skills` is only the set of core skills shipped with
the engine; `atlas skill hub` copies it, plus any extra folders you name, into the store (additive,
never overwrites). `atlas skill link` shows the plan and `atlas skill link --apply` makes the links,
backing up each replaced copy under `bridge/archive/`. Skills a client does not already have are only
linked with `--all`, because every skill adds always-on context. `atlas onboard` runs this as the
`skills` step.

`atlas skill copy` is the copy-based alternative (T-244: one home, clients get copies, not symlinks): it
gives `claude`, `codex` and `gemini` a real copy of every hub skill, whole directories included. It is a
dry run until `--apply`; a link into the hub is just unlinked, any other link or a differing real
directory is moved into a timestamped backup under `bridge/archive/`, and a skill that contains a
symlink is reported as `failed` instead of copied. Entries the hub does not name are left alone.
