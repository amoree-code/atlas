# Profiles

A profile is a JSON file describing one agent configuration: which provider to run, which
model, what role/skills to present to it, and what it is allowed to read, write, or run.

## Storage and loading

Profiles live at `<workspace>/profiles/<name>.json` (see [workspace.md](workspace.md)).
`loadProfile(name)` (`src/infrastructure/filesystem/profile-loader.ts`) reads `<name>.json` from that
directory and validates it against the schema below.

## Schema (`src/domain/profiles/profile.ts`)

```ts
{
  name: string,                                        // non-empty
  description: string,                                  // default ""
  version: string,                                      // non-empty, default "1.0.0"
  provider: "claude" | "codex" | "gemini" | "antigravity",
  model: string,                                        // non-empty
  role: string,                                         // non-empty
  skills: string[],                                      // default []
  allowedPaths: string[],                                // default []
  allowedCommands: string[],                             // default []
  writePolicy: "none" | "workspace" | "allowed-paths",  // default "none"
  contextSources: string[],                              // default []
}
```

Validation is via Zod (`profileSchema` in `profile.ts`, applied by
`validateProfile` in `profile-validator.ts`); an invalid profile throws before an agent run
starts. `description` and `version` are both optional on disk (they default to `""` and
`"1.0.0"`), so profiles written before these fields existed keep loading unchanged.

## Fields in use today

- `provider` and `model` select which provider CLI runs and are passed through to it
  (see [providers.md](providers.md)).
- `contextSources` and `allowedPaths` bound what `buildContext` reads into the prompt —
  a source path is only included if it resolves inside one of `allowedPaths`
  (see [context.md](context.md)).
- `skills`, `allowedCommands`, `writePolicy`, and `role` are part of the schema and are
  carried on every loaded profile, for provider-specific and policy use; the current
  runtime does not yet enforce `allowedCommands` or `writePolicy` itself.
- `description` is a free-text summary of what the profile is for; it has no runtime effect.
- `version` is a human-assigned label for a profile's configuration (bump it when you
  change a profile's fields); it participates in the identity described below.

## Session reproducibility (`profileIdentity`)

A profile file can be edited after a session has already been created from it, so a
session records more than the profile's name: `profileIdentity(profile)`
(`src/domain/profiles/profile.ts`) hashes every field of a `Profile` (sha256 of a fixed-key
JSON encoding, including `version`) into one deterministic string. `runAgent`
(`src/application/runs/run-agent.ts`) computes this hash when it creates a session and
stores it as `Session.profileIdentity` (persisted as the `profile_identity` column in
`sessions.sqlite`, see [sessions.md](sessions.md)).

Two profiles with identical fields — including `version` — always produce the same
identity; changing any field, including bumping `version` alone, changes it. This lets a
session be traced back to the exact profile configuration that produced it, independent of
how the profile file on disk has changed since. Sessions created before this field existed
read back with `profileIdentity: ""`.

## Profile vs. project vs. session

These three are easy to conflate because all three can be named on the command line, but
they answer different questions:

- **Profile** (`profiles/<name>.json`) — *how* an agent runs: provider, model, role,
  skills, and read/write policy. It is configuration, reused across many runs, and owns no
  data of its own.
- **Project** (`projects/<name>/`) — *what* the work is about: the tickets, plans, and
  private notes for one piece of work (see the workspace-root layout in
  [workspace.md](workspace.md)). A project has no execution configuration; a profile
  points at paths, it does not define what lives there.
- **Session** (one row in `sessions/sessions.sqlite`) — *one run*: the record of a single
  agent invocation, which profile (and, via `profileIdentity`, which exact profile
  configuration) produced it, its status, and its transcript of events (see
  [sessions.md](sessions.md)). A session is created fresh every time `atlas run` starts,
  and can be resumed, but it never becomes a profile or a project.

A profile is loaded by name for a run; the run happens against a project's files (via
`cwd`/`allowedPaths`); the result of that run is one session.

## Default profile

`atlas setup` writes `profiles/default.json` from
`templates/profiles/default.json` if it does not already exist:

```json
{
  "name": "default",
  "description": "General-purpose assistant profile for ad-hoc work across the active workspace.",
  "version": "1.0.0",
  "provider": "claude",
  "model": "sonnet",
  "role": "general assistant",
  "skills": [],
  "allowedPaths": ["."],
  "allowedCommands": [],
  "writePolicy": "workspace",
  "contextSources": []
}
```

## Role profiles

`templates/profiles/` also ships public starter templates for three other roles; unlike
`default.json`, `atlas setup` does not install these automatically — copy the one you need
into `profiles/` under the workspace root:

- **`strategist.json`** — plans and reasons about approach; `writePolicy: "none"`.
- **`developer.json`** — implements and fixes code; `writePolicy: "workspace"`.
- **`reviewer.json`** — reviews changes and reports findings; `writePolicy: "none"`.

The active instances a workspace actually runs with live only at `<workspace
root>/profiles/*.json` — never inside `engine/`.

## Skill roots

Profile skill names resolve progressively in this order: public `engine/skills/`, private
`personal/skills/`, then the active project's `skills/` directory under
`projects/<project>/skills/`. Each private or project root uses the same `index.json` and
`<category>/<name>/SKILL.md` contract as the public catalog. The first matching name wins;
duplicate profile names are loaded once, and the combined instructions are bounded before
they are added to the provider prompt. Private and project skill content never belongs in
the public engine repository.

The local Agent Skills validator runs with `pnpm check:skills`. CI runs the same pinned
Node.js script (`scripts/validate-skills.mjs`) and checks every public `SKILL.md` against its
frontmatter, directory name, and `skills/index.json` entry. It is a development check only;
runtime skill loading does not invoke CI tooling.
