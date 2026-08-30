---
name: session-end
description: Optional lightweight session cleanup - a session record plus a sweep for anything task completion did not already save. Use when the user says wrap up, session end, save context, done for now, or log this session.
---

# Session end

> **This is not the memory mechanism.** If your setup does automatic bookkeeping at task
> completion (see the task-loop policy/rule, if configured), the daily log, tasks file,
> memory, and registry are normally already current by the time this runs. This is
> cleanup and a session-level narrative — nothing should depend on the user remembering
> to run it.
>
> So: **check before you write.** For each step below, if it is already recorded, say
> "already current" and move on. Do not duplicate an entry.

Only for meaningful work. A single question answered, a file read, a one-line fix —
skip it and say so.

## Steps

1. **Session record.** Write to
   `~/.ai-os/sessions/$(date +%Y)/$(date +%m)/$(date +%Y-%m-%d-%H%M)-<project>-<topic>.md`.
   `<topic>` is 1–3 kebab-case words. Create the month folder if needed. Fill **Files
   changed** from `git status --short` and `git log` for this session — not from memory.
   Omit any section with nothing real in it. **Next step** must be concrete enough to
   start from cold.

2. **Daily log.** Append the meaningful events to today's
   `~/.ai-os/daily/$(date +%Y/%m/%Y-%m-%d)/log.md`. Decisions, completions, problems and
   their fixes, discoveries. Not a narration of the session. Create today's folder first
   if it doesn't exist.

3. **Project memory** — only if something durable changed:
   - a decision → the repo's own decisions file
   - a new rule for this codebase → the repo's own conventions file
   - a bug or gotcha that will bite again → the repo's own known-issues file
   - the project's situation moved → the repo's own context file

   Nothing durable changed? Skip this step. Say you skipped it.

4. **Tasks.** Update `~/.ai-os/projects/tasks.md` — close what's done, add what surfaced,
   restate next actions. Keep the format.

5. **Registry.** Update this project's **Last** and **Next action** cells in
   `~/.ai-os/projects/registry.md`. Nothing else.

6. **Global memory** — only if it's stable, true across projects, and not already
   recorded. This is rare. When in doubt, don't.

7. **End-of-day.** If the user is stopping for the day, also write today's `summary.md`:
   Completed · Progress · Decisions · Problems · Solutions · Carry Forward ·
   Memory Candidates. Build it from the day's log, not from this session alone.

## Rules

- Each layer answers a different question. **Never paste the same paragraph into two files.**
- No secrets, no env values, no tokens — anywhere.
- Don't commit or push anything unless asked.
- Report which files you touched, in one line each.
