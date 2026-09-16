# Atlas

Atlas is a local-first runtime for running Claude, Codex, Gemini, Antigravity, and Hermes as
headless agents inside one workspace. It manages profiles, bounded context,
sessions, artifacts, and local hooks without a hosted service.

## Quick start

Install the published package when available:

```bash
npm install --global atlas
atlas setup
```

After installation, `atlas` opens a short first-run wizard automatically when the private
workspace does not exist. Use `atlas --yes` for the recommended non-interactive defaults.

For a local checkout, use the development commands below instead.

```bash
git clone https://github.com/amoree-code/atlas.git atlas
cd atlas
pnpm install
pnpm build
node dist/main.js setup
```

Connect an Obsidian vault during setup, or connect it later:

```bash
atlas setup --obsidian /path/to/Obsidian
atlas obsidian connect /path/to/Obsidian
atlas obsidian discover
atlas obsidian sync
```

The connection is read-only by default. Use `--read-write` only when Atlas is explicitly
allowed to write notes. The local runtime watches the connected vault while `atlas service`
is running.

Expose the same vault tools to an AI client through a provider-neutral stdio MCP server:

```bash
atlas mcp config
atlas obsidian mcp
```

`atlas mcp config` prints the client configuration; it does not write into client-owned
configuration files or store credentials.

The Atlas MCP server exposes read-only workspace tools, resources, and review prompts.
Local `stdio` clients provide the connection consent; Atlas keeps write and execution
approval inside its policy boundary.

By default, `setup` creates the Atlas workspace as a private sibling directory next to
this repository (e.g. `atlas/` next to `atlas/engine/`), not inside it, and installs
user-level startup integration pointed at this repository's `dist/main.js`. Later logins
start the local runtime automatically. Set `ATLAS_ROOT` to use a different workspace
location instead.

Run an agent:

```bash
node dist/main.js run --profile default --prompt "Review this project"
```

Open a provider through Atlas's managed PTY boundary when interactive use is
required:

```bash
atlas client open hermes
atlas client open claude
atlas client status
```

`atlas run` is the full-head path. Direct provider commands remain transparent
terminal-shim compatibility paths with an explicitly recorded `observed`
control level. See [entry-point contract](docs/entry-points.md).

Inspect or resume a saved session:

```bash
node dist/main.js session list
node dist/main.js session show <session-id>
node dist/main.js session resume <session-id> "Continue the review"
node dist/main.js session promote <session-id> knowledge/results --approve
```

Promotion is explicit: it copies a bounded, redacted provider result into private Atlas
knowledge and records the source session. It never promotes a session implicitly.

Continue the same task from any registered client with a compact Atlas-owned handoff:

```bash
atlas handoff create --ticket T-193 --next "Run verification"
atlas handoff context <handoff-id>
atlas run --profile reviewer --client codex --ticket T-193 --handoff <handoff-id> --prompt "Continue"
atlas idea save "Short title" "Raw idea text"
atlas daily start
```

Capture an idea without a provider subscription:

```bash
atlas capture add "An idea to review later"
atlas capture list
atlas capture promote <id> knowledge/results

# Learn a skill candidate from a completed session; review it before activation
atlas skill learn <completed-session-id>
atlas skill review <candidate-id> promoted

# Workspace health (read-only)
atlas doctor
atlas doctor --json

# Safe repair preview; apply only after reviewing the output
atlas repair
atlas repair --apply
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
├── system/                 private profiles, sessions, config, governance, integrations, and runtime
└── archive/                private retained legacy history
```

`personal/`, `projects/`, `system/`, and `archive/` are private workspace data. They are ignored
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

Build and run the isolated test image:

```bash
docker build -t atlas-test .
docker run --rm atlas-test
```

The image validates the Atlas engine and test suite. Provider CLIs and their credentials
remain on the host and are not included in the image.

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
