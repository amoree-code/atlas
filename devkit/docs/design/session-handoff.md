# Automatic new-session handoff

```text
Status:    implemented, verified
Authority: describes real code — cli/atlas-tickets, ~/atlas/context/atlas-context,
           adapters/claude-code/ai-atlas-resume, adapters/claude-code/ai-atlas-turn-checkpoint,
           tests/test-session-handoff.py, tests/test-turn-checkpoint.py, T-035
```

This is the mechanism by which a genuinely new Claude Code session, opened with a normal
first message and nothing pasted, already knows what the previous session was doing. It
is a distinct system from three other things that share vocabulary with it — see
[Why `catch-up` is unrelated](#why-catch-up-is-unrelated) below.

There are two layers, and they are deliberately kept from merging into one:

1. **The pointer** (`latest.md`) — a manually-triggered, semantically real checkpoint.
   Everything below this line describes it, and it is unchanged by layer 2.
2. **The turn journal** (`turns.jsonl`, T-035) — an automatic, semantic-free safety net
   that records one bounded entry per completed response, so a session that ends without
   anyone running a manual checkpoint still leaves an honest boundary record behind. See
   [Automatic Checkpoint — the turn journal](#automatic-checkpoint--the-turn-journal)
   near the end of this document. It reads the pointer; it never writes it.

## What creates a checkpoint

`atlas tickets checkpoint <ID> --note "..." --next "..." [--blockers "..."]`. This is the
**only** writer. There is no automatic trigger: Claude Code exposes `SessionEnd`, `Stop`
and `PreCompact` hook events, but none of them carry the semantic judgment a checkpoint
needs (what actually landed, what the next action concretely is) — that judgment stays
with whoever is closing out the work, model or owner, informed by `atlas lifecycle`'s
CONTINUE/CHECKPOINT/COMPACT/FRESH/HANDOFF read. `atlas lifecycle` prints the exact
checkpoint command it recommends; it does not run it. This is a documented limitation,
not an oversight — see [Unsupported by the current runtime](#unsupported-by-the-current-runtime).

A successful checkpoint write also calls `write_handoff_pointer()`, which regenerates
`$ATLAS_HOME/runtime/session-handoffs/latest.md` as its last step, after the ticket write
already succeeded. If the note/next-action/blockers text looks credential-shaped (reusing
`atlas-privacy-scan`'s own detector), the pointer write is skipped and reported on
stderr — the ticket itself is still written normally.

## The pointer — what is authoritative, what is not

`latest.md` is a **routing pointer**, never a history:

```
ticket           the ticket id
checkpointed_at  when
state            one line — what landed
next_action      one line — the ticket's next action
blockers         one line, only if real
read_with        the exact command to read the full ticket
status           pending | consumed
```

The ticket (`projects/<project>/tickets/<ID>/task.md`) remains the only authoritative
record — objective, files changed, verification, risks, log, artifacts all stay there.
`latest.md` never duplicates them, and is always fully overwritten, never appended to.
Safe to delete at any time; the next checkpoint regenerates it.

## What happens at `SessionStart`

`~/.claude/settings.json` registers `adapters/claude-code/ai-atlas-resume` as a
`SessionStart` hook. On every new session (startup, resume, clear, or after compaction)
it runs `atlas context --resume --json` through the standard launcher and, only if a
pending handoff exists, emits it as `hookSpecificOutput.additionalContext` — text folded
into the new session's first turn, not a tool result the model has to go read.

Emits nothing when: there is no pointer, the pointer is already `consumed`, the pointer
is malformed, or Atlas cannot be resolved on this machine at all (missing launcher,
missing settings, missing repo). The hook always exits 0 — a broken installation must
never block a session from starting.

**This was verified, not assumed.** `SessionStart` support for `additionalContext` was
proven with a real, isolated, headless `claude --settings <throwaway>.json -p "<prompt
with no marker>"` run before this hook was written (see the hook's own docstring). The
same proof is reproducible on demand — `tests/test-session-handoff.py`'s
`test_real_claude_session_discovers_pending_handoff`, gated behind
`ATLAS_TEST_REAL_CLAUDE=1` because it makes a real API call — and was re-run during this
implementation: a real `claude -p` subprocess, given a prompt naming no ticket, replied
with the pending ticket id from a temporary real pointer. That is the difference between
"a file was written" and "the model actually received it."

## What the injected context says, and does not say

```
Atlas: a previous session left a pending checkpoint for <ticket>.
This is routing information only — read the ticket before acting on it.
Checkpointed: <timestamp>
State: <one line>
Next action: <one line>
Blockers: <one line, if any>
Read the full ticket with: atlas context <ticket>
```

It never claims the previous conversation was restored. It never runs the next action.
It never executes anything named inside the pointer — every field is interpolated into a
text string for the model to read, never passed to a shell or subprocess. If the next
action needs owner approval, the new session is expected to stop and ask, exactly as it
would have without a handoff — automatic discovery is not automatic authorization.

## Consumption semantics

`status: pending` → the first successful `--resume` prints it and flips it to `consumed`,
atomically (`os.replace` after a same-name temp-file write), and **only after** the print
already succeeded. A read failure, a parse failure (malformed pointer), or a render
failure all leave `pending` untouched — nothing is marked consumed on a failure path.

The flip itself is compare-and-swap: it re-reads the file immediately before writing and
only proceeds if ticket, checkpoint timestamp and status still match what was just
rendered. A newer checkpoint written in that narrow window is left alone, still pending —
a second session never silently loses a fresher handoff to a race with an older one.

A second `--resume` after consumption reports "no pending handoff." Any new checkpoint
overwrites the whole file, including `status`, so it is pending again with no special
handling required.

**Known, accepted limitation:** consumption fires on the first `SessionStart` after a
checkpoint, including an unrelated one-off session in a different directory — there is no
signal here that distinguishes "the owner is genuinely resuming this work" from "some new
session happened to start first."

## Why `catch-up` is unrelated

Three other things in this workspace use "handoff" or "resume" vocabulary. None of them
are this system, none of them were modified to build this system, and this system does
not call any of them:

- **`catch-up` (skill)** — a user- or model-invoked read of "where did we leave off,"
  built from `atlas context`, session records and git log. It is pull-based and requires
  the skill to be invoked. It has zero code dependency on the pointer, the checkpoint
  writer, or the `SessionStart` adapter, and nothing here calls it. Automatic handoff
  works identically whether `catch-up` exists, is disabled, is outdated, or is never
  invoked.
- **`atlas-handoff` (CLI)** — agent-to-agent task delegation with an owner-approval gate
  and a declared transport (`prepare`/`approve`/`send`/`receive`). Unrelated concern:
  moving a task between AI clients with explicit consent, not a session discovering its
  own continuation point.
- **`session-handoff` (skill)** — produces a portable, copy-by-hand packet for moving
  work to a different Claude account or a genuinely fresh conversation. Explicitly
  documents that it is not for routine checkpoint/continue — that is this system's job.

The separation is architectural, not incidental: the pointer writer
(`cli/atlas-tickets`), the pointer reader (`atlas context --resume`), and the
`SessionStart` adapter (`ai-atlas-resume`) do not import, shell out to, or reference any
of the three above, and none of those three were touched while building this.

## Unsupported by the current runtime

- **No context-percentage or usage-limit event.** Claude Code does not expose a signal
  for "context is about to run out" or "the usage limit was just hit." `atlas lifecycle`
  approximates this with heuristics (turn count, cache-read ratio) and recommends a
  checkpoint; it cannot trigger one, because the runtime gives it no hook for that
  moment. Not invented here.
- **No automatic write to `latest.md` at `PreCompact` or `Stop`.** Both hooks exist and
  fire (confirmed), but writing a *semantic* checkpoint (a ticket, a real next action)
  needs judgment neither payload supplies. T-035 (below) wires both events to a
  semantic-free turn journal instead of inventing content for the pointer.
- **Unattended continuation after a usage limit** (§G of the originating brief) is
  explicitly a separate, opt-in feature with its own delay/attempt/notification
  semantics. It is not implemented, and nothing in this system starts unattended work for
  an existing task without that separate, explicit opt-in.

## Automatic Checkpoint — the turn journal

```text
Ticket:    T-035
Files:     adapters/claude-code/ai-atlas-turn-checkpoint, tests/test-turn-checkpoint.py
Hooks:     Stop, PreCompact (both registered in ~/.claude/settings.json, async)
```

Every completed response, and every compaction boundary, appends at most one JSON line to
`$ATLAS_HOME/runtime/session-handoffs/turns.jsonl` — bounded to 500 lines / 512,000 bytes
with oldest-first eviction, deduplicated per `(session_id, prompt_id, hook_event_name)` so
a duplicate `Stop` firing never doubles a record.

**It reads `latest.md`; it never writes it.** When a real manual checkpoint already names
a ticket, that ticket's `state`/`next_action`/`blockers` are carried into the turn record
verbatim (re-scanned for credential shapes, redacted if matched) and labeled as
carried-forward, not re-verified. When no pointer exists, every semantic field is written
as an explicit `"unavailable — ..."` string naming why — never guessed from
`last_assistant_message` (present in the real `Stop` payload) or from the transcript
(named by `transcript_path`, but never read by this hook). `verification` and
`changed_files` are always `"unavailable"`: no hook payload observed carries either.

This is a deliberate, load-bearing boundary, not an oversight: promoting a turn record
into `latest.md` — and therefore into what the next `SessionStart` shows — would require
this hook to decide a ticket, a state and a next action on its own, which is exactly the
invention the design forbids. The pointer stays exactly as authoritative, and exactly as
manually-triggered, as it was before T-035. See T-035's ticket record for the full
acceptance criteria, risks and the real end-to-end proof (a genuine `claude -p` call
through the actual installed `~/.claude/settings.json`, not a throwaway probe).

## Reproducing the real integration tests

```bash
cd ~/atlas/engine
python3 tests/test-session-handoff.py                            # 44 offline, no API call
ATLAS_TEST_REAL_CLAUDE=1 python3 tests/test-session-handoff.py    # + the real claude -p proof

python3 tests/test-turn-checkpoint.py                             # 43 offline, no API call
ATLAS_TEST_REAL_CLAUDE=1 python3 tests/test-turn-checkpoint.py    # + a real multi-turn session
```

The real-session test in `test-session-handoff.py` writes a temporary pointer at the real
`~/atlas/runtime/session-handoffs/latest.md`, runs an unmodified `claude -p` with a
prompt that names no ticket, asserts the reply contains the pointer's ticket id, then
restores whatever was there before (or removes the file if nothing was). The real-session
test in `test-turn-checkpoint.py` runs several real completed responses in one resumed
session with no manual checkpoint in between, confirms journal records exist anyway, then
restores the real journal and pointer to their prior state.
