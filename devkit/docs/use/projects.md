# Projects

Projects keep state that belongs to one codebase or area of work. They live under
`$ATLAS_HOME/projects/<project>/` and are separate from global memory.

## Project-owned directories

Create only what the project needs:

```text
memory/      project facts, decisions, and lessons
rules/       project-specific conventions
knowledge/   domain knowledge
context/     current milestone, blockers, and next actions
```

The cross-project views, when present, remain directly under `$ATLAS_HOME/projects/`.

## Scope and isolation

A project does not automatically inherit another project's state, and project facts do not
become global memory by accident. Promote a fact deliberately when it is true beyond one
project; reference global facts from a project instead of copying them.

The active project is resolved from the current working directory and the project registry.
Use:

```bash
atlas project <id>
atlas context
atlas tickets list
```

Project-local work tracking is not a separate supported CLI workflow yet. Use Atlas tickets
and session commands for governed work, while keeping project context in the project folder.
