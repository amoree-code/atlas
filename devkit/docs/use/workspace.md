# Your workspace

`~/atlas` is yours. Atlas writes into it at `init` and reads from it forever after; it
never owns it, never publishes it, and never overwrites what you have put there.

```
~/atlas/
├── personal/             your long-lived information
│   ├── daily/               daily logs
│   ├── memory/              the 8-section memory store
│   ├── professional/        professional material outside the memory store
│   ├── knowledge/           what work taught the system — 7 kinds
│   └── templates/           reusable document templates
├── projects/             registry · backlog · project-owned work and context
├── internal/             Atlas machinery and governance
│   ├── config/              settings, model routing, profile
│   ├── governance/
│   │   ├── rules/           canonical behavioral rules
│   │   └── policies/        private policy inputs (privacy terms)
│   ├── schemas/             private data schemas — reserved
│   ├── extensions/
│   │   ├── skills/          your own skills
│   │   └── agents/          canonical agent definitions
│   ├── helpers/             operational helper scripts
│   └── runtime/             transient generated state
├── user/
│   └── 00-inbox/            unprocessed, waiting for triage
├── mcp/                  reserved — global MCP namespace, not created by init
├── plugins/              reserved — your capability configuration, not created by init
└── internal/sessions/    session records — one per sitting, immutable once written
```

`personal/` is the human-facing durable layer, `projects/` is project-owned work, and
`internal/` is the machine-facing layer. Set `ATLAS_HOME` to put the workspace somewhere
else. Why the shape is split this way is in `docs/design/workspace-structure.md`.

`mcp/` and `plugins/` are reserved names with ownership rules rather than directories that
exist on a fresh workspace: `atlas init` creates everything above them and neither of
those two, because there is nothing yet to put in either.

> The workspace's reserved `plugins/` keeps that spelling for now, while the *public*
> capability directory was renamed `plugins/` -> `capabilities/` on 2026-09-03. The two
> are different things — one is your configuration, the other is shipped software — and
> the workspace name will be reconciled in its own change rather than silently here.

## What's true about you, and what a project taught the system

`personal/memory/` and `personal/knowledge/` are different things that are easy to
conflate. The short version: memory is what's true about *you*, knowledge is what a task
*taught* the system, and they are never merged. Practical detail — global vs. project
memory, resolution order, how your client reaches the store — is in `docs/use/memory.md`.
The conceptual model and the test that settles ambiguous cases is in
`docs/design/memory-architecture.md`.

## Project state

A project that accumulates its own persistent state gets a directory under
`projects/<project>/`, created on demand. What lives there, isolation rules, and
how the active project is determined are in `docs/use/projects.md`.

## MCP, adapters, capabilities and domains

Four concepts that must not be collapsed:

- **Adapter** — how one AI client reaches Atlas. `docs/use/adapters.md`.
- **Capability** (a `plugin`) — something Atlas can *do*. `docs/use/capabilities.md`.
- **Domain** — an area of work that names which capabilities it would need, and executes
  nothing. `docs/use/domains.md`.
- **MCP** — the protocol/server mechanism that may deliver a capability. `mcp/` is a
  reserved namespace, owned by Atlas rather than any agent, skill, project or client.
  There are currently zero Atlas-managed servers; the namespace exists so one can be added
  without inventing where it goes.

## Configuration

```
Atlas defaults  <  your configuration  <  project configuration
```

Your values win over defaults; a project's win over yours. A future update **may add** a
key you do not have, but **never changes** one you have set, and a key removed from the
defaults is left alone — deleting it is your call. `atlas doctor` reports which new
default keys exist that your config lacks; it adds nothing. There is no schema validation
and no migration system yet, deliberately.

## Templates are seeds, not a sync

`atlas init` copies a template only where nothing exists at the destination. After that,
the template and your file are two unrelated documents. **Divergence is the expected
steady state, not a defect.** Once you edit a seeded file it is yours; changing a template
in the public repository has no effect on any existing workspace, and nothing ever
reapplies one over your version. `init` reports which files differ so you can look; it
will not act.

The operational scripts under the public `templates/runtime/` are *not* seeded into your
workspace — `init` only walks `templates/workspace/`.

## Skills: yours win

```
resolution order:  ~/atlas/internal/extensions/skills   →   <atlas>/skills
```

Public skills stay in the public repository and are **not** copied into your workspace at
init — copying would turn software into your files and make it impossible to update. When
a skill name exists in both places, **yours wins**, and nothing will ever overwrite,
modify or delete it. `atlas doctor` lists which of your skills are shadowing a public one.

## Versioning and privacy

Versioning your workspace and keeping the public repository publishable are both covered
in `docs/use/safety.md`.
