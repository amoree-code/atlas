# Memory architecture

## Four kinds of context, never merged

| Layer | Answers | Lives | Lifespan |
|---|---|---|---|
| **Memory** | *what is true about you and your world?* | `~/.ai-os/memory/<section>/` | years |
| **Knowledge** | *what did work teach us that saves effort next time?* | `~/.ai-os/knowledge/<kind>/` | until superseded |
| **Session** | *what are we doing right now?* | `~/.ai-os/sessions/` | one session |
| **Daily** | *what happened today?* | `~/.ai-os/daily/YYYY/MM/DD/` | one day |

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
directory — not copies, and not asking the user to repeat themselves per folder. See
`adapters/claude-code/` for how the Claude Code adapter handles this.

## Retrieval discipline

Read the index (`memory/MEMORY.md`, `knowledge/README.md`) first, then open only the
files a task actually needs. Loading the whole store for every request defeats the
purpose — knowledge and memory exist specifically to avoid re-deriving what's already
known, which only works if retrieval stays targeted.
