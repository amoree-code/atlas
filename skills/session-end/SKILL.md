---
name: session-end
description: Optional lightweight session cleanup - a session record plus a sweep for anything task completion did not already save. Use when the user says wrap up, session end, save context, done for now, or log this session.
---

# Session end

> **This is not the memory mechanism.** Work state is saved at **task completion**,
> automatically, by `{{profile.agents.curator}}` and `{{profile.agents.scribe}}` (see the task-loop rule). By the
> time this skill runs, the daily log, `tasks.md`, memory, and the registry are normally
> already current. This is cleanup and a session-level narrative — nothing depends on the
> user remembering to run it.
>
> So: **check before you write.** For each step below, if it is already recorded, say
> "already current" and move on. Do not duplicate an entry, and do not rewrite a log line
> that `{{profile.agents.scribe}}` wrote. Delegate the writing to `{{profile.agents.scribe}}` ({{profile.agents.bookkeeping}}); this never
> needs {{profile.agents.reasoning}}.

Only for meaningful work. A single question answered, a file read, a one-line fix —
skip it and say so.

## Steps

1. **Session record.** Write to
   `~/.ai-os/sessions/$(date +%Y)/$(date +%m)/$(date +%Y-%m-%d-%H%M)-<project>-<topic>.md`
   using `{{profile.templates_dir}}/session.md`. `<topic>` is 1–3
   kebab-case words. Create the month folder if needed. Fill **Files changed** from
   `git status --short` and `git log` for this session — not from memory. Omit any
   template section with nothing real in it. **Next step** must be concrete enough to
   start from cold.

2. **Daily log.** Append the meaningful events to today's
   `~/.ai-os/personal/daily/$(date +%Y/%m/%Y-%m-%d)/log.md`. Decisions, completions, problems and
   their fixes, discoveries. Not a narration of the session. Run
   `{{profile.scripts_dir}}/day-start.sh` first if today's folder doesn't exist.

3. **Project memory** — only if something durable changed:
   - a decision → `<repo>/{{client.project_memory}}decisions.md` (template: `templates/decision.md`)
   - a new rule for this codebase → `<repo>/{{client.project_memory}}conventions.md`
   - a bug or gotcha that will bite again → `<repo>/{{client.project_memory}}known-issues.md`
   - the project's situation moved → `<repo>/{{client.project_memory}}context.md` and the
     **Status** section of `<repo>/{{client.project_context}}`

   Nothing durable changed? Skip this step. Say you skipped it.

4. **Tasks.** Update `~/.ai-os/projects/tasks.md` — close what's done, add
   what surfaced, restate next actions. Keep the format.

5. **Registry.** Update this project's **Last** and **Next action** cells in
   `~/.ai-os/projects/registry.md`. Nothing else.

6. **Global memory** — only if it passes §5 of the workspace `{{client.project_context}}`: stable, true
   across projects, not already recorded. This is rare. When in doubt, don't.

7. **End-of-day.** If the user is stopping for the day, also write today's `summary.md`:
   Completed · Progress · Decisions · Problems · Solutions · Carry Forward ·
   Memory Candidates. Build it from the day's log, not from this session alone.

## Rules

- Each layer answers a different question. **Never paste the same paragraph into two files.**
- No secrets, no env values, no tokens — anywhere.
- Don't commit or push anything unless asked.
- Report which files you touched, in one line each.
