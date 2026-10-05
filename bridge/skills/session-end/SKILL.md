---
name: session-end
description: Optional lightweight session cleanup - a session record plus a sweep for anything task completion did not already save. Use when the user says wrap up, session end, save context, done for now, or log this session.
---

# Session end

> **This is not the memory mechanism.** Work state is saved at **task completion**,
> automatically, by `memory-curator` and `task-scribe` (see the task-loop rule). By the
> time this skill runs, the daily log, `backlog.md`, memory, and the registry are normally
> already current. This is cleanup and a session-level narrative — nothing depends on the
> user remembering to run it.
>
> So: **check before you write.** For each step below, if it is already recorded, say
> "already current" and move on. Do not duplicate an entry, and do not rewrite a log line
> that `task-scribe` wrote. Delegate the writing to `task-scribe` (Haiku); this never
> needs Opus.

Only for meaningful work. A single question answered, a file read, a one-line fix —
skip it and say so.

## Steps

1. **Session record.** Write to
   `~/ocean/sessions/$(date +%Y)/$(date +%m)/$(date +%Y-%m-%d-%H%M)-<project>-<topic>.md`
   using `~/ocean/brain/06-templates/session.md`. `<topic>` is 1–3 kebab-case words.
   Create the year and month folders if they don't exist. Fill **Files changed** from
   `git status --short` and `git log` for this session — not from memory. Omit any
   template section with nothing real in it. **Next step** must be concrete enough to
   start from cold.

   Not to be confused with `~/ocean/kernel/bridge/sessions/` — that is the runtime's
   SQLite store and its machine-generated summaries. **Never write there by hand.**

2. **Daily log.** Append the meaningful events to the `## Work log` section of today's
   `~/ocean/brain/01-daily/$(date +%Y-%m-%d).md` — one flat file per date, not a folder.
   Decisions, completions, problems and their fixes, discoveries. Not a narration of the
   session. Run `~/ocean/kernel/scripts/day-start.sh` first if today's file doesn't exist.

3. **Knowledge** — only if something durable came out of the session:
   - a decision, with the rejected options → `~/ocean/brain/05-knowledge/decisions/<slug>.md`
     (template: `~/ocean/brain/06-templates/decision.md`)
   - a hard problem solved → `~/ocean/brain/05-knowledge/solutions/<slug>.md`
   - a surprising fact about a tool → `~/ocean/brain/05-knowledge/discoveries/<slug>.md`
   - something that failed and should not be retried → `~/ocean/brain/05-knowledge/failures/<slug>.md`
   - the project's situation moved → the **Status** section of that project's `AGENTS.md`

   Nothing durable changed? Skip this step. Say you skipped it.

4. **Backlog.** Update `~/ocean/brain/04-projects/backlog.md` — close what's done, add what
   surfaced, restate next actions. Keep the format. **A task's own record declares its
   status, not this file** — don't contradict `tasks/<ID>/task.md`.

5. **Registry.** Update this project's **Last** and **Next action** cells in
   `~/ocean/brain/04-projects/registry.md`. Nothing else.

6. **Personal memory** — only if it is stable, true across projects, and not already
   recorded: `~/ocean/brain/02-personal/`, read its index first. This is rare. When in
   doubt, don't.

7. **End-of-day.** If the user is stopping for the day, also fill today's remaining daily
   sections — `## Decisions`, `## Problems`, `## Next`. Build them from the whole day's
   log, not from this session alone.

## Rules

- Each layer answers a different question. **Never paste the same paragraph into two files.**
- No secrets, no env values, no tokens — anywhere.
- Don't commit or push anything unless asked.
- Report which files you touched, in one line each.
