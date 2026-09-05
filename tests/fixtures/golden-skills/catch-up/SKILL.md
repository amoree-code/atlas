---
name: catch-up
description: Reconstruct where work left off - current project, last objective, what is done, what remains, blockers, and the next action. Use when the user says continue, where were we, catch me up, resume, or what was I doing.
---

# Catch up

Rebuild context so the user never has to re-explain. Answer in the chat; write nothing.

## Steps

0. **A pasted handoff packet?** If the user's message already contains a
   `session-handoff` packet (or points at one), read that first — it is a purpose-built
   reconstruction artifact and answers step 3 directly without steps 1-2. Otherwise
   continue below.

1. **Identify the project.** In order:
   - `pwd` — inside a repo under `~/Documents/`? That's it.
   - Otherwise the most recent session record: `ls -t ~/.ai-os/internal/sessions/*/*/*.md | head -1`
   - Otherwise ask, offering the `active` rows from the registry.

2. **Read, in this order, stopping when you can answer:**
   - if the project uses the ticket system: `ai-os context` (or `ai-os context <ID>` for
     a named ticket) — it is derived from the live record every time, so it cannot be
     stale, and it is cheaper than a session record
   - the repo's `CLAUDE.md` (its **Status** section)
   - the newest session record for that project:
     `ls -t ~/.ai-os/internal/sessions/*/*/*-<project>-*.md | head -1`
   - that project's rows in `~/.ai-os/projects/tasks.md`
   - `git -C <repo> log --oneline -5` and `git -C <repo> status --short`

3. **Report, in this shape, short:**
   ```
   Project · branch
   Last worked: <date> — <objective>
   Done:      <2-4 bullets>
   Remaining: <2-4 bullets>
   Blockers:  <or none>
   Next:      <the single next action>
   ```

4. Reconcile the record against reality: if the session record's Next step is already in
   the git log, say so and give the *actual* next step.

## Rules

- **Do not read the whole workspace.** Four files at most.
- If the project has `graph-out` and the user's next question is structural ("where
  does X live", "what depends on Y"), query the graph rather than opening files. For
  resuming context, the session record and git log are enough — don't query it here.
- If there's no session record, say so plainly and rebuild from git log + status alone.
- Don't start working. Report, then wait — unless the user already said "continue and do it".
