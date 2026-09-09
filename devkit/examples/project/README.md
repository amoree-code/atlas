# Example: a project

A minimal, complete instance of the project + ticket contract (`schemas/task.md`), for
`a-project` — a fictional project, not a real one.

```
a-project/
  index.md              the work board — one ticket, in the generated table
  context/
    state.md              why it's built this way
    roadmap.md             where it's going
  tickets/
    EXMPL-001/
      task.md              the ticket record itself — the only mandatory file
```

Read [`a-project/tickets/EXMPL-001/task.md`](a-project/tickets/EXMPL-001/task.md) first —
it is a complete, filled-in `task.md` covering every required section in
`schemas/task.md` §4 (Objective, Definition of done, Next action, Verification,
Blockers, Log), with a real (if trivial) frontmatter. `index.md`'s ticket table is what
`atlas tickets index --write` would generate from that one record.

`context/state.md` and `context/roadmap.md` are the two files `cli/atlas-context`
actually reads by name for a project (see its `read_next` block) — the rest of what a
context directory can hold is project-specific and optional; see
`templates/context/README.md`.

`a-project` and `EXMPL-001` are placeholders — a real project uses its own registry key
as the directory name and its own scope prefix (`AIOS`, `OPS`, or a project key from
`projects/registry.md`) for ticket ids.
