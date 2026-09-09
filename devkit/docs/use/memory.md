# Memory and knowledge

Atlas keeps two durable stores separate:

| Store | Question it answers | Location |
|---|---|---|
| Memory | What is true about you? | `$ATLAS_HOME/personal/memory/` |
| Knowledge | What did work teach the system? | `$ATLAS_HOME/personal/knowledge/` |

The default `$ATLAS_HOME` is `~/atlas`. Both stores are private and remain outside the
public engine repository.

## Commands

```bash
atlas memory status
atlas memory doctor
atlas memory attach
atlas memory attach --here
```

`status` shows the canonical store and declared mounts. `doctor` validates memory and
knowledge health without changing files. `attach` creates a non-destructive link for a
client mount; `--here` limits it to the current project.

## Global and project scope

Global memory is independent of a project. Project-owned state belongs under
`$ATLAS_HOME/projects/<project>/` and may contain `memory/`, `rules/`, `knowledge/`, and
`context/`. Moving a fact between project state and global memory is an explicit decision;
Atlas never duplicates it automatically.

When scopes overlap, the practical order is:

```text
system rules -> global memory -> project rules -> project memory
              -> project knowledge -> project context -> session
```

Read the index first, then only the files needed for the task. Loading the whole store
defeats the reason it exists.

## Client mounts

Some clients keep their native memory in client-owned directories. Their adapter declares
where those mounts are; core owns validation and attachment. The current adapter
integration is under `agentic/integrations/adapters/claude-code/`.

The mount is an access path, not a second store. A broken, recursive, stale, or real
directory where a managed link is expected is reported by `atlas memory doctor`.
