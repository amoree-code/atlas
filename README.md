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

## What's public vs. private

| | Lives | Contains |
|---|---|---|
| **This repo (public)** | wherever you clone it | engine concepts, schemas, policies, adapters, reusable skill *templates*, CLI |
| **Your workspace (private)** | `~/.ai-os/` | your actual memory, knowledge, projects, sessions, daily context, config |

Nothing under `~/.ai-os/` is ever read by, or copied into, this repository. `ai-os init`
writes *into* `~/.ai-os/` from this repo's templates; it never writes the other way.

## Status: V0.1 — foundation

This is early. V0.1's only goal is a clean, vendor-neutral foundation: the public/private
split, the CLI foundation (`init` / `doctor` / `status`), the memory and knowledge storage
boundary, a policy abstraction (currently just Git push protection), and one working
adapter (Claude Code). It deliberately does **not** yet include an autonomous task engine,
a multi-agent system, a full model router, browser/computer automation, additional MCP
servers, or a GUI. See `docs/design-philosophy.md` for why, and the project roadmap for
what comes after V0.1.

## Layout

```
ai-os/
├── adapters/claude-code/   how Claude Code enforces AI OS policies today
├── policies/               policy definitions (currently: git push approval)
├── cli/                    ai-os-init · ai-os-doctor · ai-os-status
├── templates/
│   ├── workspace/           the ~/.ai-os/ shape, placeholder data only
│   ├── skills/                the canonical skill set, client-agnostic
│   └── scripts/                the canonical workspace scripts
└── docs/
```

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

Not yet ready for general use — `cli/ai-os-init` currently assumes a single-user, local
setup and has only been exercised against one machine. Treat it as a working sketch, not
a released tool.
