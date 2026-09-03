# Memory architecture

## Five kinds of context, never merged

| Layer | Answers | Lives | Lifespan |
|---|---|---|---|
| **Memory** | *what is true about you and your world?* | `~/.ai-os/user/02-personal/memory/<section>/` | years |
| **Knowledge** | *what did work teach us that saves effort next time?* | `~/.ai-os/user/05-knowledge/<kind>/` | until superseded |
| **Session** | *what are we doing right now?* | `~/.ai-os/sessions/` | one session |
| **Daily** | *what happened today?* | `~/.ai-os/user/01-daily/YYYY/MM/YYYY-MM-DD/` | one day |
| **Project memory** | *what is true about ONE project?* | `~/.ai-os/user/04-projects/<project>/memory/` | life of the project |

Global memory is client-independent and project-independent: one store, every client
reaches it through its adapter's mounts. Project memory is scoped to its project and
never loads into another project's context. Movement between the two layers is always
explicit — the curator promotes a project fact to global memory only deliberately, and
global facts are referenced (not copied) into project context. Resolution order when
working inside a project: system rules → global memory → project rules → project
memory → project knowledge → project context → session; system rules are never
overridden.

## The test that settles ambiguity

> **Would this still be true if you never wrote another line of code?**
> Yes → Memory. No → Knowledge.

Worked examples (illustrative, not literal):

| Fact | Goes to | Why |
|---|---|---|
| "I'm planning to relocate next year" | `memory/travel/` | true about the person |
| "This library requires config X for our framework version" | `knowledge/research/` | true about the world, learned by working |
| "This project uses library X for state management" | `memory/projects/<project>` | persistent project context |
| "We chose X over Y because Z" | `knowledge/decisions/` | a decision, with alternatives |
| "That bug was caused by X" | `knowledge/technical-solutions/` | reusable solution |
| "Approach X doesn't work because Y" | `knowledge/failures/` | prevents a repeat |
| "Ran the test suite, 12 passed" | nowhere | session noise, not durable |

## Cross-domain facts get one canonical home

A fact that touches two sections lives in the one matching its *meaning*; the other
section links to it, never repeats it. Example shape: if a relocation depends on a
specific program or credential, the *program* is `education/`, the *move itself* —
timing, priority, destination — is `travel/`. Neither restates the other.

## Global scoping

Some AI clients scope their own native memory tool to the current working directory,
which means memory written in one folder can be invisible from another. If your adapter
has this quirk, the fix is one canonical store plus symlinks into it per project
directory — not copies, and not asking the user to repeat themselves per folder.

The engine that does this is core and client-agnostic: `cli/ai-os-memory` owns the store,
the validation, and the non-destructive attach. It contains no client name. An adapter
with the quirk declares one integration point in its manifest —

```yaml
integrates:
  memory.mounts: { command: <exe>, format: newline-paths, verified: true }
```

— and answers a single question: *where does my client keep its memory directories?* Core
decides everything else. `adapters/claude-code/ai-memory-mounts` is the only implementation
today, holding the two facts that are Claude Code's and not memory's: the
`~/.claude/projects/` location and the working-directory slug rule. Any other client gets
the same engine by declaring the same point — there is one memory engine, never a fork per
client.

## Retrieval discipline

Read the index (`memory/MEMORY.md`, `knowledge/README.md`) first, then open only the
files a task actually needs. Loading the whole store for every request defeats the
purpose — knowledge and memory exist specifically to avoid re-deriving what's already
known, which only works if retrieval stays targeted.
