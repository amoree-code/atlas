# Memory — main sections

**Memory answers: *what is true about you and your world?***
If a fact would still be true even if you never wrote another line of code, it belongs
here. If it's something a task *taught* you, it belongs in `../knowledge/` instead.

`MEMORY.md` is the retrieval index — read it first, then open only what the task needs.

| Section | Purpose | Belongs here | Does **not** belong here |
|---|---|---|---|
| `identity/` | stable facts about you | name, location, languages, contact, links | anything that changes with a job or a project |
| `education/` | academic background and study plans | credentials, certificates, in-progress study | *when* you move → `travel/`; research findings → `knowledge/research/` |
| `career/` | professional context | employers, experience, domain, direction | per-codebase detail → `projects/`; solved bugs → `knowledge/` |
| `projects/` | persistent context per codebase | purpose, long-term architecture, standing constraints, status | implementation detail → the repo itself; task results → `knowledge/task-results/` |
| `goals/` | what you're aiming at | long-term goals, with links to the owning section | the detail behind a goal — link to it, don't copy it |
| `travel/` | relocation, if relevant | timeline, priority order, destination, decisions | the underlying reason (e.g. a scholarship) → its own section |
| `preferences/` | how you want the agent to work | communication, workflow, tooling, stack defaults | a one-off request from a single conversation |
| `interests/` | persistent non-work threads | ongoing side interests | a topic you asked about once |

## Rules

**One canonical home per fact.** A fact that touches two sections lives in the one that
matches its *meaning*; the other section links to it. Example: if a scholarship is tied
to a relocation, the scholarship track lives in `education/`, the move itself in
`travel/` — neither repeats the other.

**No country, company, or one-off topic gets its own top-level section.** Those are
values inside the sections above, not new sections.

**Promotion is deliberate.** Most of what's said in a session belongs nowhere. Promote
only what will still be true and useful in a month, isn't already recorded, and isn't
derivable from a repo or its git history. Never store secrets or temporary debugging
state.

**Contradictions are surfaced, not resolved.** New information that conflicts with an
existing record goes in `CONFLICTS.md` with both versions, and you decide.

**A missing file means missing information.** Don't create a file to fill a shape that
has nothing real in it yet.
