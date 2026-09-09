---
name: session-handoff
description: Produce a compact, portable handoff packet so another Claude session or Claude account can continue this exact work without replaying the conversation. Use when the lifecycle reading is HANDOFF or FRESH, or the user says continue this on another account, switch sessions, or hand this off.
---

# Session handoff

This is **continuation state, not a summary**. A summary describes what happened; this
packet is the minimum a cold session needs to *act* — the next command, not a recap of
the last ten. It answers `atlas lifecycle`'s `HANDOFF` decision, and is also the right
tool under `FRESH` when the destination is a different Claude account rather than the
same one restarting.

## When to run this

- `atlas lifecycle` (or `session-end`, which calls it) returned `HANDOFF`.
- The user is moving the work to a different Claude account or a fresh conversation and
  says so.
- Never run this for routine `CHECKPOINT`/`CONTINUE` — that is what
  `atlas tickets checkpoint` is for, and duplicating it here would just be a second
  writer for the same state.

## What this is not

- Not `session-end` — that persists durable state and is optional cleanup; this produces
  a *portable artifact* meant to leave the room. They compose: `session-end` may
  checkpoint first, then call this.
- Not `atlas-handoff` (the CLI) — that is agent-to-agent task delegation with an owner
  approval gate and a declared transport. This skill never sends anything; it is text the
  user copies themselves, by hand, wherever they choose.
- Not a conversation export. Raw history, tool logs, full ticket logs and full
  architecture docs never go in it — the entire point is to escape accumulated context,
  not carry it forward.

## Steps

1. **Checkpoint first, if there's a live ticket and durable progress isn't already
   recorded.** `atlas tickets checkpoint <ID> --note "..." --next "..."`. The packet below
   points at the ticket rather than re-stating its contents — if the ticket is stale, the
   pointer is worthless.

2. **Pull the grounding, don't restate it.** `atlas context <ID>` (or `atlas context` with
   no live ticket) gives project, ticket, objective, next action and verification state
   for free — read it, don't copy it into the packet by hand.

3. **Write the packet** using the shape below. Every section is optional — omit a section
   with nothing real in it rather than writing "None."

4. **Scan for sensitive content before handing it over.** Never include credentials, API
   keys, tokens, cookies, session identifiers, or personal information beyond what the
   task genuinely needs. If in doubt, point at the file instead of quoting it.

5. **Report the packet's size.** A packet that has grown past its budget (see below) is a
   sign something durable should have been checkpointed instead of copied in.

## Packet shape

```
Project: <name>            Ticket: <ID or none>
Objective: <one line — what done looks like>

Done:
- <2-5 bullets, only what's verified, not narrated>

Current state / decisions:
- <frozen invariants or choices that constrain what comes next, only if non-obvious>

Files changed / currently important:
- <paths, not diffs>

Blockers / owner decisions needed:
- <or omit this section entirely>

Next action: <the single next concrete step>

Verify with: <the exact command(s) worth rerunning>

Read next (don't copy, just point):
- <ticket path>
- <one or two other durable references, only if the next step needs them>

Git: branch <name> · <n> uncommitted · push needs explicit owner approval, every repo
```

## Size budget

Target **under ~500 words / ~3,000 characters** — a few hundred to low thousands of
tokens, not tens of thousands. This is a guideline grounded in what `atlas context`'s own
packet already proves is enough to resume a ticket (its cold packet measures in the
low thousands of bytes); a handoff carrying meaningfully more than that is almost always
copying something that belongs in a durable reference instead. There is no hard-coded
kill switch — say the size, and let the reader judge — but a packet several times this
size has very likely smuggled in raw history and should be re-cut.

## Portability rule

Read the packet back and ask: does understanding it depend on anything from this
conversation that isn't written down here or reachable by the pointers in "Read next"?
If yes, it is not portable yet — either add the missing fact (if it's small) or point at
where it durably lives (if it's not).
