---
name: day-start
description: Start the working day - create today's daily folder and write a brief and plan grounded in real repo state, open tasks, and recent sessions. Use when the user says start my day, good morning, what should I work on, daily brief, or plan today.
---

# Day start

Produce a brief the user can read in under a minute, and a plan grounded in evidence —
not invented priorities.

## Steps

1. Create the folder and stubs:
   ```bash
   ~/atlas/internal/helpers/day-start.sh
   ```
   It prints the path and never overwrites existing files. If `brief.md` already has
   content beyond the stub headings, the day has started — offer to update it instead of
   rewriting, and stop here unless the user wants a rewrite.

2. Gather state — one call:
   ```bash
   ~/atlas/internal/helpers/context.sh
   ```

3. Read `~/atlas/projects/registry.md` (the `active` rows only) and, if the
   last session record names a project, that project's `.claude/memory/context.md`.

4. Write `brief.md`. Sections: **Focus today** · **Active projects** · **Unfinished from
   last session** · **Reminders**. Rules:
   - Every line traces to something you actually read — a task, a dirty branch, a session
     record's Next step. No filler.
   - Name the project and the concrete next action, not the topic.
   - Under 25 lines. If there's little to say, say little.

5. Write `plan.md`. P1/P2/P3 from the task file's priorities and the brief. Put anything
   waiting on someone else under **Blockers**, and last session's Remaining under
   **Carry-over**.

## Rules

- **Never invent a deadline.** If no due date is recorded, there isn't one.
- Don't list a dormant project as focus just to fill the page.
- Don't re-run this if today's brief already exists — read it instead.
