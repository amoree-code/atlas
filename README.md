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

## Three layers, three owners

| | Lives | Owns |
|---|---|---|
| **Public** (this repo) | wherever you clone it | code, CLI, adapters, policies, schemas, public skills, templates, docs, tests |
| **Runtime** | `~/.ai` | hooks, runtime scripts, client integration — *an implementation detail of V0.x* |
| **Private** (your workspace) | `~/.ai-os/` | your memory, knowledge, projects, sessions, daily records, config, skills |

**Access is not ownership.** The runtime reads and writes your workspace constantly —
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

## Status: V0.1.3 — the contract

This is early. V0.1's goal was a clean, vendor-neutral foundation: the public/private
split, the CLI (`init` / `doctor` / `status`), the memory and knowledge storage boundary,
a policy abstraction, and one working adapter (Claude Code). V0.1.3 makes the boundary
between the three layers explicit and *executable* — `init` is ownership-aware and
non-destructive, `doctor` verifies the contract, and `privacy-scan` checks that this
repository is still publishable. It deliberately does **not** yet include an autonomous task engine,
a multi-agent system, a full model router, browser/computer automation, additional MCP
servers, or a GUI. See `docs/design-philosophy.md` for why, and the project roadmap for
what comes after V0.1.

## Layout

```
ai-os/
├── cli/                    ai-os · init · doctor · status · workspace · privacy-scan
├── skills/                 public skills — yours in ~/.ai-os/skills override these
├── policies/               the contract, privacy classification, git approval
├── adapters/claude-code/   how Claude Code enforces AI OS policies today
├── templates/
│   ├── workspace/          seeds for a new ~/.ai-os — placeholder data only
│   └── runtime/            seeds for the runtime layer
├── tests/
└── docs/
```

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
```

Requires `bash`, `git`, `python3`. No dependencies, no build step. Full walkthrough in
[docs/installation.md](docs/installation.md); what lives in your workspace and who owns it
in [docs/workspace.md](docs/workspace.md).

Not yet ready for general use — this assumes a single-user local setup and has only been
exercised against one machine. Treat it as a working sketch, not a released tool.

```bash
tests/test-contract.sh   # 52 checks on the contract, in a throwaway workspace
```
