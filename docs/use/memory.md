# Memory and knowledge

**Memory** is what is true about *you* — who you are, what you are working toward, how you
like to work. It changes slowly. `personal/memory/` has eight sections:
`identity`, `education`, `career`, `projects`, `goals`, `travel`, `preferences`,
`interests`.

**Knowledge** is what a *task* taught the system — a solved problem, a decision and its
alternatives, an approach that failed. It changes with every project. `personal/knowledge/`
has seven kinds: `task-results`, `technical-solutions`, `decisions`, `architecture`,
`research`, `discoveries`, `failures`.

The test when it is ambiguous: *would this still be true if you never wrote another line
of code?* Yes → memory. No → knowledge. They are never merged. The full model, with worked
examples, is in `docs/design/memory-architecture.md`.

## Global memory and project memory

`personal/memory/` is the **single global memory store** — what is true about you,
independent of any project and of any AI client. There is exactly one, and every client
reaches that one store through its adapter's mounts. It is never duplicated per client.

A project that accumulates its own persistent state gets a directory under
`projects/<project>/` instead — see `docs/use/projects.md`. Movement between the
two layers is always an explicit act: a project fact is *promoted* to global memory
deliberately, and global facts are *referenced* from a project rather than copied into it.

**Resolution order** when working inside a project, narrower scopes overriding broader
ones — except system rules, which are never overridden:

```
system rules → global memory → project rules → project memory
             → project knowledge → project context → session
```

## How your client reaches your memory

One canonical store, `~/.ai-os/personal/memory`, and every client points at it.

Some AI clients scope their own native memory tool to the current working directory —
Claude Code does, at `~/.claude/projects/<cwd-slug>/memory/` — which means memory written
in one project folder is invisible from another. The fix is a symlink per project
directory, all pointing at the single store, not a copy per client and not asking you to
repeat yourself per folder. `ai-os doctor` verifies every one of them and fails on: a
broken link, a target outside the workspace, a link to a stale pre-cutover store, a real
directory where a link should be (that is a second, invisible memory store), a recursive
link, and links that disagree about where memory lives.

The links are **access**. The memory itself is still yours, still private, still outside
the public repository. See `docs/design/public-private.md`.

The engine behind this is core and client-agnostic: `cli/ai-os-memory` owns the store, the
validation, and the non-destructive attach. An adapter with the working-directory quirk
declares one integration point in its manifest — `integrates: { memory.mounts: ... }` —
and answers a single question: *where does my client keep its memory directories?* Core
decides everything else. `adapters/claude-code/` is the only implementation today; any
other client gets the same engine by declaring the same point.

## Retrieval discipline

Read the index (`memory/MEMORY.md`, `knowledge/README.md`) first, then open only the files
a task actually needs. Loading the whole store for every request defeats the purpose —
memory and knowledge exist specifically to avoid re-deriving what's already known, which
only works if retrieval stays targeted.

> Project memory is a **documented layer**, not yet an engine feature: `ai-os memory
> doctor` validates the global store. Skills and agents follow the doctrine above.
