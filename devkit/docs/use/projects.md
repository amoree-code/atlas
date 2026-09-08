# Projects

A project that accumulates its own persistent state gets a directory under
`projects/<project>/`, holding any of:

```
memory/      decisions, history, lessons that belong to this project only
rules/       project-specific conventions and constraints
knowledge/   project domain knowledge
context/     current milestone, blockers, active work
```

These directories are created **when there is something to put in them** — never
scaffolded in advance, so a registry of twenty projects does not imply twenty
directories. `registry.md` and `tasks.md` stay directly under `projects/` as the
cross-project views: the full project list, and the cross-project task list.

## Isolation

Project memory is scoped to its project: one project's memory never loads into another's
context, and never becomes global on its own. Movement between project state and your
global memory is always an explicit act — a project fact is *promoted* to global memory
deliberately, and global facts are *referenced* from a project rather than copied into it.
See `docs/use/memory.md` for the resolution order this participates in.

## Which project is active

The active project is determined from the working directory, matched against
`registry.md`. There is no project selector and no stored "current project" state — moving
into a project's directory is what makes it active.

## Where the CLI stands today

Project memory is a **documented layer**, not yet an engine feature. `atlas memory doctor`
validates the global store; skills and agents follow the doctrine above by convention, not
because anything enforces it mechanically. Documenting a workflow ahead of the tooling
that would enforce it is deliberate here — see `docs/design/decisions.md` for why Atlas
stays small on purpose rather than building the enforcement first.

Project-local **work tracking** — turning `projects/tasks.md` into something a
project owns end to end — is designed but not implemented, so it is not documented as a
user workflow yet.
