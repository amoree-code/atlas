<!--
  Skeleton per schemas/task.md (the ticket contract).
  Copy this file to projects/<project>/tickets/<ticket-id>/task.md and fill in every
  placeholder below (<angle-bracket> text). Optional sections — `## Scope`,
  `## Sessions` — and any artifact file are added later, only when there is
  something real to put in them (schemas/task.md §5).
-->
---
id: <ticket-id> # e.g. AIOS-042 — MUST match this directory's name
title: <one line — what the work is, not how>
state: todo # todo | active | paused | blocked | done | cancelled
project: <project> # a key from projects/registry.md, or `-` for none
opened: <YYYY-MM-DD>
updated: <YYYY-MM-DD> # bump this whenever the file changes
artifacts: [] # file names that exist beside this task.md — add one only when it's written

# Optional — durable classifications of the work, never a limit and never enforced:
# class: medium              # small | medium | large — how much reasoning the work needs
# expected_context: small    # small | medium | large — how much context it should take
---

## Objective

<what done looks like from outside, one or two lines>

## Definition of done

<the observable condition that proves it works>

## Next action

<the single next concrete thing to do — enough to start cold, without the transcript>

## Verification

<the command that proves the work, and its last actual result — update after every run>

## Blockers

None.

## Log

- <YYYY-MM-DD> — <what landed, with the file it touched>
