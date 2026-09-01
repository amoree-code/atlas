# Your workspace

`~/.ai-os` is yours. AI OS writes into it at `init` and reads from it forever after; it
never owns it, never publishes it, and never overwrites what you have put there.

```
~/.ai-os/
├── user/                 your information
│   ├── 00-inbox/            unprocessed, waiting for triage
│   ├── 01-daily/            daily logs
│   ├── 02-personal/         personal information — memory/ is the 8-section store
│   ├── 03-professional/     professional material outside the memory store
│   ├── 04-projects/         registry · tasks · per-project context (on demand)
│   ├── 05-knowledge/        what work taught the system — 7 kinds
│   └── 06-templates/        reusable document templates
├── system/               AI-OS configuration and governance
│   ├── rules/               canonical behavioral rules
│   ├── policies/            private policy inputs (privacy terms)
│   ├── schemas/             private data schemas — reserved
│   └── config/              settings, model routing, profile
├── mcp/                  global MCP namespace — registry/ servers/ config/
├── plugins/              your capability configuration (reserved)
├── skills/               your own skills
├── agents/               canonical agent definitions
├── scripts/              operational helper scripts
├── sessions/             session records and the live task checkpoint
└── runtime/              transient generated state
```

user/ is the human-facing half; system/ is the machine-facing half. Set `AI_OS_HOME` to put
it somewhere else.

## Memory and knowledge are not the same thing

**Memory** is what is true about *you* — who you are, what you are working toward, how you
like to work. It changes slowly. `user/02-personal/memory/` has eight sections: `identity`, `education`,
`career`, `projects`, `goals`, `travel`, `preferences`, `interests`.

**Knowledge** is what a *task* taught the system — a solved problem, a decision and its
alternatives, an approach that failed. It changes with every project. `user/05-knowledge/` has
seven kinds: `task-results`, `technical-solutions`, `decisions`, `architecture`,
`research`, `discoveries`, `failures`.

The test when it is ambiguous: *would this still be true if you never wrote another line
of code?* Yes → memory. No → knowledge. They are never merged. See
`docs/memory-architecture.md`.

## Global memory and project memory

`user/02-personal/memory/` is the **single global memory store** — what is true about you,
independent of any project and of any AI client. There is exactly one, and every client
reaches that one store through its adapter's mounts. It is never duplicated per client.

A project that accumulates its own persistent state gets a directory under
`user/04-projects/<project>/`, holding any of:

```
memory/      decisions, history, lessons that belong to this project only
rules/       project-specific conventions and constraints
knowledge/   project domain knowledge
context/     current milestone, blockers, active work
```

These directories are created **when there is something to put in them** — never
scaffolded in advance, so a registry of twenty projects does not imply twenty
directories. `registry.md` and `tasks.md` stay at the `04-projects/` level as the
cross-project views.

**Isolation.** Project memory is scoped to its project: one project's memory never loads
into another's context, and never becomes global on its own. Movement between the layers
is always an explicit act — a project fact is *promoted* to global memory deliberately,
and global facts are *referenced* from a project rather than copied into it.

**Resolution order** when working inside a project, narrower scopes overriding broader
ones — except system rules, which are never overridden:

```
system rules → global memory → project rules → project memory
             → project knowledge → project context → session
```

The active project is determined from the working directory matched against `registry.md`.
There is no project selector and no stored "current project" state.

> Project memory is a **documented layer**, not yet an engine feature: `ai-os memory
> doctor` validates the global store. Skills and agents follow the doctrine above.

## MCP, adapters and capabilities

`mcp/` is the **global MCP namespace**, owned by AI OS rather than by any agent, skill,
project, or client. Three states are kept distinct:

| State | Meaning |
|---|---|
| **AI-OS-managed** | a server AI OS installs and offers to every capable client — lives in `mcp/servers/`, listed in `mcp/registry/` |
| **client-installed** | a server declared by a client's own config; it stays client-owned and is never absorbed |
| **observed metadata** | what AI OS knows about client MCP without owning it — manifests record `provides.mcp` as verified-but-not-written |

**There are currently zero AI-OS-managed servers.** The directories are a reserved
namespace with an ownership rule, not an implementation. There is deliberately no
`agents/*/mcp/` or `skills/*/mcp/`.

`plugins/` is reserved for **capabilities** — what AI OS can *do*: software delivery,
browser control, automation. A capability is defined once, globally, and reached by every
client through its adapter; there is never a per-client copy of one. **No capabilities
ship today** — the public `plugins/` is empty by design, and its contract is
`schemas/plugin.schema.md`.

Three layers that must not be collapsed: a **capability** (a `plugin`) is something AI OS
can do, **MCP** is the protocol/server mechanism that may deliver one, and an **adapter**
is how a single AI client consumes AI OS. Adapters are public software in
`adapters/<client>/`, contract `schemas/adapter.schema.md` — never duplicated inside your
workspace.

Until V0.4 the public `plugins/` held the client manifests, which are adapters. That
inversion is resolved: `adapters/` = clients, `plugins/` = capabilities.

## How the runtime reaches your memory

One canonical store, `~/.ai-os/user/02-personal/memory`, and every client points at it.

Claude Code scopes its native memory per working directory
(`~/.claude/projects/<cwd-slug>/memory/`), which means memory written in one project is
invisible from another. The fix is a symlink per project directory, all pointing at the
single store. `ai-os doctor` verifies every one of them and fails on: a broken link, a
target outside the workspace, a link to a stale pre-cutover store, a real directory where
a link should be (that is a second, invisible memory store), a recursive link, and links
that disagree about where memory lives.

The links are **access**. The memory is still yours, still private, still outside the
public repository. See `docs/public-private-contract.md`.

## Configuration

```
AI OS defaults  <  your configuration  <  project configuration
```

Your values win over defaults; a project's win over yours.

- A future update **may add** a key you do not have.
- A future update **never changes** a key you have set.
- A key removed from the defaults is left alone. Deleting it is your call.

`ai-os doctor` reports which new default keys exist that your config lacks. It adds
nothing. There is no schema validation and no migration system yet, deliberately.

## Templates are seeds, not a sync

`ai-os init` copies a template only where nothing exists at the destination. After that,
the template and your file are two unrelated documents.

**Divergence is the expected steady state, not a defect.** Once you edit a seeded file it
is yours. Changing a template in the public repository has no effect on any existing
workspace, and nothing ever reapplies one over your version. `init` reports which files
differ so you can look; it will not act.

Runtime scripts are *not* seeded into your workspace — they belong to the runtime layer.
(Earlier versions seeded them into `config/scripts/`, which created a second copy nothing
ever read. Fixed in V0.1.3.)

## Skills: yours win

```
resolution order:  ~/.ai-os/skills   →   <ai-os>/skills
```

Public skills stay in the public repository. They are **not** copied into your workspace
at init — copying would turn software into your files and make it impossible to update.
When a skill name exists in both places, **yours wins**, and nothing will ever overwrite,
modify or delete it. `ai-os doctor` lists which of your skills are shadowing a public one.

## Versioning — local only

The workspace is a git repository with **no remote, and it must stay that way.** Local git
gives you history, rollback and audit. That is not publishing.

```bash
ai-os workspace status     # tracked state plus the safety checks
ai-os workspace snapshot   # one commit per completed task, not per file edit
git -C ~/.ai-os log        # history
git -C ~/.ai-os diff       # what changed
git -C ~/.ai-os restore <path>
```

A `pre-push` hook refuses pushes; a `pre-commit` hook blocks credential-shaped strings
from entering history at all — a local commit is still a permanent record. `ai-os init`
never creates the repository and never creates a remote. See
`docs/workspace-versioning.md`.

## Privacy terms

`system/policies/privacy-terms.txt` holds your identifying strings — name, handles, emails,
employers, private repository names. `ai-os privacy-scan` uses them to check that the
public repository contains none of them.

They live here, not in the public repository, for a reason: **a scanner that hardcoded
your real name and employer would itself be the leak it exists to prevent.** The public
half ships only generic shapes. Without this file the scan still runs, but only on those
generic patterns — names and repository names are not checked, and `doctor` warns you.
