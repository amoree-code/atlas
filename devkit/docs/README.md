# Docs

Three kinds of document here, and they answer different questions.

- **`use/`** — *how do I do X?* Practical, task-shaped, written for someone running the
  CLI right now.
- **`design/`** — *why does it work this way?* Rationale, contracts and the reasoning
  behind a choice, written for someone deciding whether to change something.
- **`examples/`** — worked examples when a workflow needs one. No examples folder is
  shipped in the current release, so it is not linked as an available guide.

A `use/` page links to the `design/` page behind it when the "why" matters; it doesn't
repeat it.

## Reading order

New here? Start with [Getting started](use/getting-started.md). It is the supported path
for the current CLI and links to the deeper pages.

### Use

| Doc | Covers |
|---|---|
| [getting-started.md](use/getting-started.md) | the fast path through everything below |
| [install.md](use/install.md) | full install and onboarding walkthrough |
| [workspace.md](use/workspace.md) | the workspace layout, config, templates, skills |
| [memory.md](use/memory.md) | memory, knowledge, and how a client reaches the store |
| [projects.md](use/projects.md) | project-scoped state and isolation |
| [adapters.md](use/adapters.md) | connecting an AI client to Atlas |
| [capabilities.md](use/capabilities.md) | what Atlas can actually do |
| [domains.md](use/domains.md) | declaring an area of work |
| [safety.md](use/safety.md) | versioning your workspace, keeping the public repo publishable |
| [mcp.md](use/mcp.md) | the bar an MCP server has to clear before you add it |

### Design

| Doc | Covers |
|---|---|
| [core.md](design/core.md) | the mechanism shared across every client and capability |
| [public-private.md](design/public-private.md) | the two-layer boundary everything else rests on |
| [workspace-structure.md](design/workspace-structure.md) | why the workspace is shaped this way |
| [governance.md](design/governance.md) | policy, authority and approval |
| [domain-delivery.md](design/domain-delivery.md) | why a domain declares and executes nothing |
| [runtime.md](design/runtime.md) | the two things "runtime" has meant, kept apart |
| [memory-architecture.md](design/memory-architecture.md) | the memory/knowledge model and the test that settles ambiguity |
| [decisions.md](design/decisions.md) | the principles, and why the system stays this small |

## Current limits

Project-local work tracking is not a supported CLI workflow yet. Projects can hold memory,
rules, knowledge, and context; use the ticket and session commands for governed work.
