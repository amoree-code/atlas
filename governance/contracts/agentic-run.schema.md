# Agentic run contract — version 1

An **Agentic run** is one bounded, generated execution record for the current Agentic
session. It coordinates planning, execution, review, and stopping, but it is not the
source of truth for ticket state, mission state, or durable work history.

## What it is not

An Agentic run is not a ticket, not a mission, not a workflow engine, and not a second
task system. Ticket records remain authoritative. The run only records the state needed
to bound one live execution.

## Persistence

One JSON file per run: `runtime/agentic/<run_id>.json`.

The directory holds generated runtime state only. It must never contain durable project
truth, ticket truth, personal knowledge, or any copied task record.

## Fields

```json
{
  "run_id": "agentic-20260908-020614-8c5c30",
  "goal": {
    "ticket": "T-101",
    "summary": "Write the run envelope contract from the approved Agentic design."
  },
  "actor": {
    "client": "atlas",
    "session_id": "session-20260908-020614"
  },
  "surface": "cli",
  "stage": "planning",
  "workflow": "plan",
  "packet": {
    "id": "pkt-001",
    "kind": "plan",
    "revision": 1
  },
  "budget": {
    "steps_max": 5,
    "steps_used": 0
  },
  "permissions": {
    "profile": "planner",
    "grant": "observe"
  },
  "claims": {
    "scope": "T-101",
    "lease": null
  },
  "confirmation": {
    "status": "confirmed",
    "ticket_ids": ["T-123"],
    "owner": {"client": "atlas", "session_id": "session-..."},
    "scope_ref": "engine/cli",
    "packet_hash": "sha256:...",
    "context_policy": {"mode": "lazy", "max_files": 0, "max_ranges": 0},
    "token_limit": 40000,
    "cost_limit_usd": 0.50,
    "confirmed_at": "2026-09-09 12:00:00"
  },
  "stop_conditions": [
    "goal-complete",
    "budget-exhausted",
    "conflict"
  ],
  "status": "active",
  "created_at": "2026-09-08 02:06:14",
  "updated_at": "2026-09-08 02:06:14",
  "approval": {
    "approval": "none",
    "approved_at": null,
    "owner_words": null
  },
  "permission_log": []
}
```

`surface` identifies the Atlas-managed entry surface (for example `cli`, `ide`,
`terminal`, or `extension`). `routing` and `events`, when present, are generated
controller evidence only; they contain references and classifications, never copied
ticket, memory, or artifact content.

The controller permits `active -> paused|blocked|completed|failed|stopped`,
`paused|blocked -> active|stopped`, and no transitions from terminal states. Every
transition requires a non-empty reason.

`approval` and `permission_log` are optional on an envelope written before T-102 — a
record without either field is still a valid run. `atlas agentic create` always writes
both (empty/`none`); any envelope naming either field must get its shape right.

## Permission boundary (T-102)

Client authority is explicit and enforceable here — never inferred from a prompt or a
transport flag. There is exactly one authority mechanism in this repository:
`atlas-capability`'s `AUTHORITY` ladder (`observe -> propose -> execute ->
execute-with-approval -> autonomous`) and its private grant ledger
(`governance/authority.yaml`, read by `granted_rung()`). `atlas agentic check` imports and
calls that mechanism directly — it does not re-derive the ladder or a second grant ledger.

### Profiles (owner decision, T-102 D1)

| profile | may request at most | notes |
|---|---|---|
| `observer` | `observe` | read-only |
| `planner` | `propose` | prepares without performing |
| `executor` | `execute` | reversible actions |
| `reviewer` | `execute-with-approval` | needs recorded approval evidence, every time |
| `admin` | *(none — see below)* | permission-management only, never a capability action |

`admin` is **not** an alias of `autonomous`. It names a permission-management role: it may
never invoke a capability directly, at any rung, under any grant. Its only actions are
permission-management actions, and those always require recorded approval evidence —
`admin` is never auto-approved, same as every other approval.

### `permissions.grant` — a declared ceiling, not a second ledger (D2, D3)

`grant` on the run is a **declared ceiling** that may only ever *lower* the target
capability's own public maximum (`capability.authority` in its manifest) — it can never
raise it. `"inherit"` means no override: the ceiling is exactly the capability's own
maximum. The run never carries or is checked against a private grant of its own; the
actual, currently-granted rung is always resolved per action, fresh, from
`atlas-capability`'s existing `granted_rung(<capability>)` — one ledger, not two.

### Scope (D4)

An action is in scope only when its declared target exactly equals `claims.scope`. No
hierarchy, no prefix or subset matching — a different or missing target is refused as
scope escalation.

### Action escalation (D5)

The exact rung-vs-grant comparison `atlas capability invoke` already makes
(`AUTHORITY.index(need) > AUTHORITY.index(have)`), reused by importing the same `AUTHORITY`
list and `granted_rung` function — not a second, independent authorization system.

### Approval evidence

Reused as-is from `atlas_mission.py`'s existing shape: `approval: "none"|"recorded"`,
`approved_at`: an ISO-style timestamp or `null`, `owner_words`: non-empty text or `null`.
Recorded at most once per run (`atlas agentic approve`); a second attempt is refused, never
overwritten. Required before any `execute-with-approval` action, and before any
permission-management action — never inferred.

### `permission_log`

Every `atlas agentic check` decision — allow or deny — is appended here: `at`, `kind`
(`capability-action`|`permission-change`), `capability` (or `null`), `target_scope`,
`profile`, `decision` (`allow`|`deny`), `reason`. A denial without a reason is not
explainable, so `reason` is required on every entry.

## Lifecycle

`active` · `paused` · `blocked` · `completed` · `failed` · `stopped`

Only `active` may continue. Every other state is terminal or paused and must not be
treated as a fresh run.

## Contract rules

- `goal.ticket` is an opaque reference to the ticket record.
- `goal.summary` is descriptive only and never replaces the ticket.
- `stage` names the current phase of the run.
- `workflow` names the bounded Agentic flow being followed.
- `packet` is the current generated packet state for this run.
- `budget` records the run-local budget only.
- `permissions` records the run's profile and its declared ceiling — never a private grant
  of its own (see Permission boundary below).
- `claims` records the run-local scope and lease view.
- `confirmation` binds a run to ticket IDs, its scope, and one packet hash. Dispatch
  refuses a run without `status: confirmed`.
- `context_policy.mode: lazy` records bounded references and budgets only; it never copies
  file contents into the run envelope. `max_files: 0` means no eager file loading.
- `surface` records the entry surface that owns this run.
- `routing` records classified references to context packets or artifacts; it is not a
  second source of truth.
- `stop_conditions` is a set of reasons that may end the run.
- The contract may only store generated runtime state under `runtime/agentic/`.

## What it may not do

- Rewrite ticket truth.
- Duplicate mission or task records.
- Store durable knowledge.
- Introduce a second authority source.
- Become a workflow engine.
