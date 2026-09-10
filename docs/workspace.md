# Workspace

Atlas separates the public **engine** (this repository) from a private **workspace** that
holds every piece of user and runtime data. Nothing under the workspace is committed to
this repository's git history.

## Layout

```text
<workspace root>/           default: the parent directory of engine/ (e.g. ~/atlas)
├── personal/                user-owned private data
├── projects/                 user-owned project data
├── profiles/                 one JSON file per profile (see profiles.md)
├── sessions/
│   └── sessions.sqlite       session store (see sessions.md)
├── config/
│   ├── policies/
│   ├── schemas/
│   ├── startup/
│   └── settings.json
├── control-plane/            private governance and permissions
├── integrations/             private client integrations
└── archive/                  private retained legacy history
```

## Root resolution (`src/paths.ts`)

- `engineRoot()` / `enginePath(...)` — always the directory containing this package
  (resolved from the running module, whether compiled under `dist/` or run under `tsx`
  from `src/`).
- `atlasRoot()` — `process.env.ATLAS_ROOT` if set (resolved to an absolute path),
  otherwise the parent directory of `engineRoot()`. This is the default private-workspace
  location: `engine/` is expected to sit inside the workspace root as a sibling of
  `personal/`, `projects/`, `profiles/`, `sessions/`, and `config/`.
- `atlasPath(...)` — joins onto `atlasRoot()`, used for `personal/` and `projects/`.
- `atlasPath(...)` — joins onto `<atlasRoot>/`, used for private workspace state.

Set `ATLAS_ROOT` to point Atlas at a different workspace root, for example to run multiple
isolated workspaces from one engine checkout.

## Bootstrap (`atlas setup`)

`src/interfaces/cli/setup-command.ts` creates the workspace on first run:

- Creates `personal/memory`, `personal/knowledge`, `personal/daily`, `personal/inbox`,
  `personal/templates`, and `projects/atlas/tickets` under the workspace root.
- Creates `config/policies`, `config/schemas`, `config/startup`, `profiles`, `sessions`,
  `control-plane`, `integrations`, and `archive` under the workspace root.
- Writes `config/settings.json` and `profiles/default.json` from the
  templates in `templates/`, without overwriting existing files.
- Installs a per-OS startup entry that launches `engine/dist/main.js service` with the
  workspace root as its working directory: a macOS `launchd` plist under
  `~/Library/LaunchAgents`, a Linux `systemd --user` unit under
  `~/.config/systemd/user`, or a Windows Startup-folder launcher script.
- Restricts `config` to `0700` permissions.

Startup always points at `engine/dist/main.js` (the built engine), never at `src/`, and
always runs with the private workspace directory as its current working directory.
