# Context template

`context/` holds a project's durable narrative — the material a cold session reads once
it already has the derived packet (`atlas context`, `cli/atlas-context`) and needs the
story behind it, not the current snapshot.

Exactly two files are read **by name**, by that tool (see its `read_next` block):

- `state.md` — why the project is built the way it is
- `roadmap.md` — where it is going

Copy both into `projects/<project>/context/` and fill in the placeholders. Anything else
placed in this directory (a charter, requirements, a project map) is a project-specific
artifact, not part of the contract — add one only when it earns its place: would a
future session be materially worse off without it? Would it be re-derived anyway? The
same test `schemas/task.md` §5 applies to a ticket artifact applies here.

Earlier revisions of this contract also read `current.md` and `checkpoint.md` by name.
Both were retired: a hand-maintained snapshot goes stale the moment the filesystem moves
past it, so the current state is derived on demand by `atlas context` instead of copied
into prose. Do not recreate those two files as part of a new project's scaffolding.

See a worked example at `docs/examples/project/a-project/context/`.
