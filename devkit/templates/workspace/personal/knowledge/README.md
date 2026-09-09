# Knowledge — reusable work experience

**Knowledge answers: *what did work teach us that saves effort next time?***
It is not a copy of Memory. Memory is about the person; Knowledge is about the work.

> **The test:** would this still be true if you never wrote another line of code?
> Yes → `../memory/`.  No → here.

Knowledge exists to **cut tokens**. Without it a task re-reads old files and re-derives
what was already established. With it, one small entry replaces that investigation.

| Section | Answers | Entry shape |
|---|---|---|
| `task-results/` | what did we finish, and what is left? | Task · Project · Objective · Result · Important changes · Verification · Remaining · Reusable knowledge |
| `technical-solutions/` | how was this hard problem solved? | Problem · Root cause · Solution · Why it worked · Files affected · Verification · Future warning |
| `decisions/` | why is it this way, and what did we reject? | Decision · Context · Options · Chosen · Reason · Consequences · Status |
| `architecture/` | how does this system fit together? | the shape, the invariants, and what must not be broken |
| `research/` | what did we find out about the outside world? | the conclusion and its support — never a raw dump |
| `discoveries/` | what surprising thing is true about our tools? | the fact, why it matters, the future warning |
| `failures/` | what did not work, so we don't retry it? | what was tried · why it failed · the fix · the lesson |

## Rules

**Check `decisions/` before proposing something contradictory.** That is the section's
whole purpose — a past decision with its reasoning beats re-arguing it.

**Small and factual.** Optimize for useful information per token. A knowledge entry that
has to be skimmed has failed. No transcripts, no narration.

**Deduplicate.** Search before writing; update an existing entry rather than adding a
near-duplicate.

**Mark verification honestly.** `verified` (we ran it) · `inferred` (we concluded it) ·
`unverified` · `outdated`. A guess recorded as verified is worse than no entry.

**Only what has future value.** Not every failed command is a `failures/` entry — only
one that would otherwise be repeated.

## Not knowledge
- Facts about you → `../memory/`
- What happened today → `../daily/`
- What happened in one session → `../../internal/sessions/`
- Where every project lives → `../projects/registry.md`
