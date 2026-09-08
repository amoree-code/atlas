# Integration contract — draft

```text
Status:    DRAFT — BOUNDARY-DEFINED (Phase G, T-022)
Authority: non-canonical
Runtime consumers: 0
`integration/` (Phase G, T-022) now exists as the reserved root this draft is the
contract for, with its own doorway doc restating the shape below. Nothing under this
draft is built: no queue, no runtime directory beyond the empty reserved root, no
orchestrator, no conflict-resolution logic. Promotion to a live, canonical contract
requires a real runtime consumer — not scheduled by this or any phase to date.
Reconciled 2026-09-08 (T-105): this file and the private workspace's copy at
`contracts/integration.schema.md` had byte-diverged (wording only — both still DRAFT,
non-canonical, zero consumers). Adopted the private copy's wording here because the
private root's own `integration/README.md` (a real file, part of the T-022 reserved
root) references this contract directly, making that the more currently-accurate
narrative. This is now the canonical copy; the private root's copy is retained as a
historical record, not edited by this reconciliation.
```

Context loading: load only when designing or reasoning about how isolated concurrent
execution work gets reconciled into canonical state. Not always-on, and not relevant to
ordinary single-session ticket work at all today.

## Naming — read this section first

```text
Capability provider/driver  ≠  Atlas work integration
```

"Integration" has meant two different things in this codebase: a capability's connection
to an external system (e.g. Playwright as the browser capability's integration — that sense
is being renamed **provider/driver**, capability-side, per `naming-collisions.md` §integration),
and, from here on, **the boundary where isolated concurrent execution results are
reconciled into canonical Atlas state**. This contract is about the second sense only. It
does not touch `capability.schema.md`'s existing provider language — that rename is a
separate, unstarted schema-rename slice, not part of this draft.

## Current source(s)

- `AIOS-020/candidate-tree.md` §`integration/` and §`runtime/` — the frozen architecture
  this draft is the contract for (`integration/` is a reserved top-level root; nothing under
  it is built yet).
- `AIOS-020/naming-collisions.md` §integration — the naming split above.
- `schemas/run.schema.md` — the existing Run contract; a Run is the thing being integrated,
  not touched by this draft.

## Future relationship

This is the draft contract for data that would eventually live under the reserved
`integration/` root. Phase G (`T-022`) created that root and its doorway doc, but not
`integration/attempts/` itself (per `candidate-tree.md`) — still deliberately absent, no
earlier than a future ticket with a real runtime consumer. This draft exists so that
future work has a shape to build against, not so it starts sooner.

---

## 1. What this is

> Worker completion ≠ canonical integration.
> Executed ≠ verified.

Integration is the **explicit, verified boundary** between "a worker finished something in
isolation" and "that result is now part of the canonical record." Nothing before that
boundary is canonical, no matter how confident the worker's own report is.

## 2. Minimum data shape

| Field | Required? | Notes |
|---|---|---|
| `source ticket` | required | the ticket this integration attempt belongs to |
| `source responsibility/work` | optional | only when the ticket is subdivided (mirrors handoff's `work` field — never forced) |
| `source run` | required | the Run that produced the result (`schemas/run.schema.md`'s `run_id`) |
| `source workspace` | required | the isolated environment the run executed in (future `runtime/workspaces/<run-id>/`) |
| `source branch/commit` | optional | only when Git-backed; `-` otherwise |
| `base revision` | required when Git-backed | what the work was based on, for conflict detection |
| `verification state` | required | `run \| not run`, and its actual result — never assumed from `executed` |
| `conflict state` | required | whether reconciling against current canonical state found a conflict |
| `dependencies` | optional | other integration attempts this one requires first, if any |
| `result/artifact references` | required | paths, never copies — see Contract design principles |
| `integration status` | required | see §3 |
| `integration attempt identity` | optional, generated | only when a source can genuinely need more than one attempt (retry after conflict) — not a mandatory id for a single-shot integration |

## 3. Suggested lifecycle

```text
pending      queued for reconciliation, not yet examined
ready        no known blocker, eligible to be checked
checking     conflict/verification check in progress
conflict     reconciliation found a conflict with canonical state; blocked
verified     the result's own verification has run and passed
integrated   accepted into canonical state — terminal, success
rejected     will not be integrated — terminal, the reason is recorded
```

This follows directly from `candidate-tree.md`'s existing rows (`integration/` = reconciling
isolated results; `Conflicts` → `integration/`; `Verification` → per-run + contract-level) —
it does not invent new stages beyond what those rows already imply. Kept small on purpose:
no sub-states, no parallel tracks, no orchestrator deciding transitions.

## 4. Safety boundary

- A result reaching `verified` means **its own** verification ran and passed — not that it
  is safe against whatever canonical state has become since the run started. `conflict`
  exists precisely to catch that gap.
- Only `integrated` means the result is now canonical. Every earlier status, including
  `verified`, is still isolated work.
- Nothing in this draft describes how conflicts are resolved, how many attempts are
  allowed, or who/what decides `ready`→`checking`. Those are orchestration questions,
  explicitly out of scope here and for Phase A generally.

## 5. What this draft does not do

- Does not create `integration/`, `integration/attempts/`, or any runtime directory.
- Does not implement conflict detection, a queue, retries, or a scheduler.
- Does not change `schemas/run.schema.md` or how a Run is created today.
- Does not rename existing "provider"/"integration" language in `capability.schema.md` —
  flagged for a future schema-rename slice, not done here.
