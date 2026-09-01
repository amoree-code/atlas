# AI OS

A portable operating layer for AI coding agents — not a Claude Code configuration.

AI OS separates the parts of an AI development setup that are genuinely reusable
(memory schema, knowledge taxonomy, skills, policies, CLI) from the parts that are
specific to one person (their actual memory, their actual projects) and one client
(how Claude Code, specifically, enforces a policy). The reusable half is this
repository. The personal half never leaves your machine.

```
                         AI OS
                           │
          ┌────────────────┼────────────────┐
          │                │                │
       Context          Execution          State
          │                │                │
       Memory           Agents            Tasks
       Knowledge        Skills            Sessions
       Projects         Tools             Events
                           │
                         Policies
                           │
                        Adapters
                           │
             ┌─────────────┼─────────────┐
             ↓             ↓             ↓
          Claude         Codex         Gemini
          Adapter        Adapter       Adapter
```

## Two layers, two owners

| | Lives | Owns |
|---|---|---|
| **Public** (this repo) | wherever you clone it | code, CLI, adapters, policies, schemas, public skills, templates, docs, tests |
| **Private** (your workspace) | `~/.ai-os/` | your memory, projects, knowledge, sessions, daily records, system config — and `runtime/` for transient generated state |

Earlier versions had a third layer, a runtime directory at `~/.ai`. It was retired in
V0.2: its engine became this repository's `cli/`, its user data moved into the private
workspace, and its transient state now lives at `~/.ai-os/runtime/`.

**Access is not ownership.** The CLI reads and writes your workspace constantly —
that is its job. It does not follow that this repository owns, tracks, or may publish any
of it. Nothing under `~/.ai-os/` is ever read by, or copied into, this repository.
`ai-os init` writes *into* `~/.ai-os/` from this repo's templates, once, and never the
other way.

See **[docs/public-private-contract.md](docs/public-private-contract.md)** — the boundary
everything else rests on, and the one `ai-os doctor` verifies.

The workspace is **private by default and versioned locally only** — a git repository
with no remote, for history, rollback and audit. Versioning is not publishing; adding a
remote, pushing, exporting, or copying workspace content into this repository all require
explicit approval. See `policies/workspace-privacy.yaml` and
`docs/workspace-versioning.md`.

## Status: V0.3 — the architecture

This is early. V0.1's goal was a clean, vendor-neutral foundation: the public/private
split, the CLI (`init` / `doctor` / `status`), the memory and knowledge storage boundary,
a policy abstraction, and one working adapter (Claude Code). V0.1.3 made that boundary
explicit and *executable* — `init` is ownership-aware and non-destructive, `doctor`
verifies the contract, and `privacy-scan` checks that this repository is still
publishable. V0.2 retired the `~/.ai` runtime layer. V0.3 gives the private workspace its
canonical shape: `user/` for everything the user owns, `system/` for configuration and
governance, and reserved namespaces for `mcp/` and capability `plugins/`. V0.4 separated
the two senses of "plugin": `adapters/` holds client integrations, `plugins/` holds
capabilities.

It deliberately does **not** yet include an autonomous task engine, a multi-agent system,
a full model router, browser/computer automation, AI-OS-managed MCP servers, capability
plugins, or a GUI. `mcp/` and `plugins/` are declared namespaces with ownership rules —
not implementations. See `docs/design-philosophy.md` for why it stays that way, and
`docs/public-private-contract.md` for the boundary everything else rests on.

## Layout

```
ai-os/                      the public repository — software only
├── cli/                    ai-os · init · doctor · status · workspace · privacy-scan · sync
├── skills/                 public skills — yours in ~/.ai-os/skills override these
├── agents/                 (none yet — agent definitions live in your workspace)
├── policies/               the contract, privacy classification, git approval
├── schemas/                adapter.schema.md (clients) · plugin.schema.md (capabilities)
├── adapters/<client>/      client integrations — manifest, hooks, policy enforcement
├── plugins/<capability>/   what AI OS can do — empty by design, none ship yet
├── templates/
│   ├── workspace/          seeds for a new ~/.ai-os — placeholder data only
│   └── runtime/            seeds for the operational scripts
├── tests/
└── docs/
```

> **Adapter vs capability.** An **adapter** answers *"how does this AI client reach
> AI OS?"* (`adapters/<client>/adapter.yaml`). A **capability** answers *"what can AI OS
> do?"* (`plugins/<id>/plugin.yaml`). Until V0.4 the client manifests lived in `plugins/`,
> inverting the two names; that is now resolved and the directories match the concepts.

Your private workspace, created by `ai-os init`, looks like this:

```
~/.ai-os/
├── user/                   everything you own
│   ├── 00-inbox/ 01-daily/ 03-professional/ 05-knowledge/ 06-templates/
│   ├── 02-personal/memory/ the single global memory store
│   └── 04-projects/        registry.md · tasks.md · <project>/ (created on demand)
├── system/                 rules · policies · schemas · config
├── mcp/                    global MCP namespace — registry/ servers/ config/
├── plugins/                your capability configuration (reserved)
├── skills/ agents/ scripts/
├── sessions/               session records and the live task checkpoint
└── runtime/                transient generated state (gitignored)
```

Full detail in [docs/workspace.md](docs/workspace.md).

Templates are **seeds, not a sync**: copied once where nothing exists, never reapplied
over a file you have edited.

## Core concepts

**Memory vs. Knowledge.** Memory is what's true about *you* — stable, changes slowly.
Knowledge is what a task *taught* the system — reusable, changes with every project. They
are never merged. See `docs/memory-architecture.md`.

**Skill vs. Tool vs. Adapter.** A skill is *how* to run a workflow. A tool is *what* the
agent can do (filesystem, git, browser). An adapter is *how* one specific AI client
(Claude Code, Codex, Gemini, …) implements AI OS concepts and policies in its own
mechanism (hooks, config format, skill format).

**Policy vs. implementation.** A policy — e.g. "pushing to a remote requires explicit
approval" — is declared once, client-agnostically, in `policies/`. Each adapter enforces
it its own way. See `policies/README.md`.

## Getting started

```bash
export PATH="$PWD/cli:$PATH"
ai-os init --dry-run     # see exactly what would happen
ai-os init               # create ~/.ai-os — never overwrites anything
ai-os doctor             # verify the contract holds
ai-os memory doctor      # verify memory + knowledge health
```

Requires `bash`, `git`, `python3`. No dependencies, no build step. Full walkthrough in
[docs/installation.md](docs/installation.md); what lives in your workspace and who owns it
in [docs/workspace.md](docs/workspace.md).

Not yet ready for general use — this assumes a single-user local setup and has only been
exercised against one machine. Treat it as a working sketch, not a released tool.

```bash
tests/test-contract.sh   # the contract suite, in a throwaway workspace
```
