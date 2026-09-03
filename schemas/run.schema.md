# Run contract — version 1

A **Run** is a bounded execution boundary: the record that lets a model perform a
multi-step sequence of capability invocations — observe, decide, invoke, verify, continue
— without that sequence being able to run forever or exceed what the user granted.

**A Run is not an agent, an orchestrator, a planner, or a workflow engine.** It never
decides which capability to use, what the next action should be, or how to solve a task.
The model remains responsible for reasoning. Run only:

```
checks · bounds · records · verifies state · refuses · terminates
```

## Why this exists

A model can already perform `observe → decide → invoke → verify → continue` through
`ai-os capability invoke` alone — no new execution model was needed for that. What was
missing was a bound: nothing stopped the same operation from being invoked indefinitely
inside a single granted authority rung. A Run is that bound, and nothing more.

## Relationship to `tasks/`

A Run may carry a `task_id` as an **opaque reference only** — a string, never parsed,
never used to open a file. Core does not read or write `tasks/` (task AIOS-002). A Run
is not a second task system: task state lives in `tasks/<ID>/task.md`, forever
convention-only; a Run's own state lives entirely in `runtime/`, and the two never merge.

## Relationship to the capability contract

A Run **wraps** `ai-os capability invoke` (`schemas/capability.schema.md`); it does not
duplicate or bypass it. Every invocation a Run performs goes through the same
`available -> allowed -> invocable -> executed -> verified` pipeline, with the same
authority ladder and the same rule that `executed` never implies `verified`. A Run can
only ever be **more** restrictive than what invoke alone would allow — never less:

```
effective authority  =  capability authority  ∩  user grant  ∩  run scope
```

Run scope can shrink what a step may attempt. It cannot grant anything invoke itself
would refuse, and there is no code path in `ai-os-run` that writes to
`system/config/authority.yaml` or otherwise elevates a grant.

**Approval is never manufactured.** Every invocation a Run makes runs with stdin closed
(`subprocess.DEVNULL`), regardless of how `ai-os run` itself was invoked. An
`execute-with-approval` operation therefore always resolves to "no terminal" inside a
Run and the Run transitions to `needs-approval` — it can never silently approve itself,
on purpose.

## Persistence

One JSON file per run: `runtime/runs/<run_id>.json`. Ephemeral, regenerable, gitignored
— the same ownership rule as browser session state (`runtime/browser/`). A Run is never
written into `tasks/`, memory, or knowledge; a result worth keeping belongs with the task
that produced it, recorded by the model, not by Run.

## Fields

```json
{
  "run_id": "run-20260901-041210-a1b2c3",
  "task_id": "AIOS-002",
  "created_at": "2026-09-01 04:12:10",
  "max_steps": 10,
  "steps_used": 3,
  "scope": ["browser.read", "browser.navigate", "browser.extract"],
  "status": "continue",
  "terminal_reason": null,
  "last_signature": "9f2c7a1b4e6d0f83",
  "repeat_count": 1,
  "invocations": [
    {
      "seq": 1, "capability": "browser", "operation": "navigate",
      "allowed": true, "executed": true, "verified": true,
      "outcome": "verified", "counted": true, "at": "2026-09-01 04:12:11"
    }
  ]
}
```

`invocations[]` records enough to answer *what capability, what operation, in what
order, was it allowed, was it executed, was it verified, why did the run stop* — nothing
more. It never stores credentials, secrets, full page contents, or large output; the
underlying capability's own stdout is already summarized to a handful of lines by
`ai-os-capability`, and Run does not expand on that.

## Budget

`max_steps` is set once, at `ai-os run create`, and is required — there is no implicit
unlimited mode and no `--unlimited`/`--no-limit`/`autonomous=true` equivalent anywhere in
this contract. `steps_used` increments only when a step actually reaches
`ai-os capability invoke` (a Run-local refusal — out of scope, run already terminal, budget
already exhausted — costs nothing, because nothing was attempted). There is no verb that
edits `max_steps` after creation: a running Run cannot extend or reset its own budget
through this CLI. Starting a new Run always starts a new budget.

A step that would exceed the budget is refused, and the Run transitions to `blocked`.

## Scope

A Run's scope is a plain list of exact `<capability>.<operation>` strings, nothing more
— no wildcards, no path syntax. An invocation naming anything outside that list is
refused before `invoke` is ever called; that refusal does not itself end the Run — the
caller may simply try an in-scope operation next.

## No-progress detection

If the same `capability.operation` with the same arguments is attempted three times in a
row (a fixed, documented bound — not a heuristic, not model-judged) with no verified
result in between, the Run transitions to `blocked` with reason `no-progress`. This is
the direct answer to the demonstrated failure mode: 12 identical, unchallenged repeats of
one operation inside a single granted rung, with nothing to ever stop it.

This bound is deliberately crude. It cannot tell a genuinely stuck loop from three
legitimate retries of a flaky, idempotent read — the contract accepts that cost in
exchange for staying deterministic rather than inventing an AI-judged loop detector.

## Lifecycle

```
continue          the Run is valid and may take further steps
completed          the caller declared a step's `verified` outcome as the completion
                    condition (--complete-on-verified), and it was met
blocked            budget exhausted, no-progress detected, an operation is unavailable
                    or not invocable, or the granted authority is below what an
                    operation (other than execute-with-approval) needs
failed             the underlying capability invocation itself failed or timed out
needs-approval      the next operation needs execute-with-approval, which a Run can
                    never supply on its own
```

Only `continue` accepts further steps. Every other status is terminal for that Run —
begin a new Run to continue working, with a fresh budget and (if still true) the same
scope.

## What a Run may not do

- Read or write anything under `tasks/`.
- Grant, elevate, or bypass an authority rung `ai-os capability invoke` would refuse.
- Approve an `execute-with-approval` operation on the caller's behalf.
- Reset, extend, or otherwise self-modify its own `max_steps`.
- Decide which capability or operation to invoke next — that stays the caller's job.
- Persist anything outside `runtime/runs/<run_id>.json`.

## Contract versioning

There is currently one version of this contract. A future incompatible version would be
declared and refused the same way the adapter and plugin contracts are — never partially
honoured.
