# Atlas

Atlas is a local-first runtime for running Claude, Codex, and Antigravity as
headless agents inside one workspace. It manages profiles, bounded context,
sessions, artifacts, and local hooks without a hosted service.

## Quick start

```bash
git clone https://github.com/amoree-code/atlas.git atlas
cd atlas
pnpm install
pnpm build
node dist/main.js setup
```

By default, `setup` creates the Atlas workspace as a private sibling directory next to
this repository (e.g. `atlas/` next to `atlas/engine/`), not inside it, and installs
user-level startup integration pointed at this repository's `dist/main.js`. Later logins
start the local runtime automatically. Set `ATLAS_ROOT` to use a different workspace
location instead.

Run an agent:

```bash
node dist/main.js run --profile default --prompt "Review this project"
```

Inspect or resume a saved session:

```bash
node dist/main.js session list
node dist/main.js session show <session-id>
node dist/main.js session resume <session-id> "Continue the review"
```

The installed provider must be available on `PATH`. Atlas does not store provider
credentials.

## Repository layout

```text
atlas/
├── engine/                 public Atlas Runtime repository
│   ├── src/                domain / application / infrastructure / interfaces
│   ├── templates/
│   ├── tests/
│   └── package.json
├── personal/               private user data
├── projects/               private project data
├── profiles/               private agent profiles
├── sessions/               private session state
├── config/                 private application config
├── control-plane/          private governance and permissions
├── integrations/           private client integrations
└── archive/                private retained legacy history
```

`personal/`, `projects/`, `profiles/`, `sessions/`, `config/`, `control-plane/`,
`integrations/`, and `archive/` are private workspace data. They are ignored
by Git and are never part of a public commit. By default they resolve to a private
workspace directory next to this repository; set `ATLAS_ROOT` to choose another
workspace root. Startup entries execute the engine from `engine/dist/main.js` while
using the private workspace as their working directory.

## Development

```bash
pnpm install
pnpm build
pnpm test
```

The test suite uses local processes and temporary SQLite databases. It does not
invoke a real provider or require an API key.

## Documentation

- [Architecture](docs/architecture.md) — layers, execution flow, and the public/private boundary
- [Workspace](docs/workspace.md) — layout, path resolution, and `atlas setup`
- [Profiles](docs/profiles.md) — schema, loading, and the default profile
- [Sessions](docs/sessions.md) — storage, status lifecycle, and CLI usage
- [Providers](docs/providers.md) — supported providers and how they are invoked
- [Context](docs/context.md) — how the prompt context is assembled and bounded
- [Security](docs/security.md) — credentials, the workspace boundary, and access control
- [Troubleshooting](docs/troubleshooting.md) — common errors and how to resolve them
- [Migration](docs/migration.md) — what changes between versions and how to move a workspace
- [Changelog](CHANGELOG.md) — versioned release notes

## License

Atlas is open source. See [LICENSE](LICENSE).
