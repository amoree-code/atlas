# Ticket contract

```text
Status:    ACCEPTED as of Phase E2 (AIOS-020/migration-plan.md) — documentation contract.
Authority: describes behavior already enforced by cli/atlas_tickets.py
           (required_fields_for, atlas_metadata_issues); reviewed against that code and
           confirmed accurate at acceptance. Nothing here is itself executable — the code
           remains the actual enforcement, this file the written-down source it answers to.
Runtime:   internal/schemas/task.md and existing schemas/ remain the legacy documentation
           of the same enforced behavior; both stay live until an explicit later cutover
           retires one in favor of the other. No CLI resolution changed by acceptance.
Reconciled 2026-09-08 (T-105): this file and the private workspace's copy at
`contracts/ticket.schema.md` had byte-diverged, differing only in this status header —
the private copy had already been promoted to ACCEPTED (Phase E2) while this one was left
at the earlier DRAFT/Phase-A wording. Re-verified against current code
(engine/cli/atlas_tickets.py still defines both functions named above) before adopting the
ACCEPTED header here. This is now the canonical copy; the private root's copy is retained
as a historical record of the acceptance decision, not edited by this reconciliation.
```

Context loading: load only for ticket create/update/validation work. Not always-on.

## Current source(s)

- `internal/schemas/task.md` (private) — the live historical contract.
- `T-001` — the actual Atlas-native frontmatter shape, in production.
- `cli/atlas_tickets.py` / `cli/atlas-tickets` — doctor's real enforced behavior.

## Future relationship

Candidate replacement/generalization of `internal/schemas/task.md` during Phase E, when
`schemas/` → `contracts/` and classification becomes per-file instead of per-root
(`candidate-tree.md` §`contracts/`). Until then this file describes intent; the files above
remain what is actually enforced.

---

## 1. Identity

Two generations, never aliased:

| Generation | Form | Status |
|---|---|---|
| Historical | `AIOS-###`, `<SCOPE>-###` | frozen, immutable, valid forever |
| Atlas-native | `T-###` | current, starting at `T-001` |

- `AIOS-001` and `T-001` never compare equal, never alias, never collide by construction.
- An id is immutable once created — no ticket is ever renumbered.
- `SCOPE` (historical) is a project registry key or `AIOS`/`OPS`; `T` is scope-less by
  design (a generation marker, not a project key).

## 2. Core fields

| Field | Required? | Meaning |
|---|---|---|
| `kind` | required, Atlas-native only | `ticket` — short visible type tag |
| `namespace` | required, Atlas-native only | `atlas.ticket` — short visible identity, never a long dotted id like `atlas.ticket.T-001` |
| `id` | required | see §1 |
| `title` | required | one line, what the ticket is, not how |
| `state` | required | see §5 (unchanged from the historical model) |
| `project` | required | registry name, or `-` for none |
| `opened_at` / `opened` | required (one of) | see §4 |
| `updated_at` / `updated` | required (one of) | see §4 |
| `artifacts` | required | manifest of files beside `task.md`; `[]` is normal and healthy |
| `class` | optional | `small`\|`medium`\|`large` — how much reasoning the work needs |
| `expected_context` | optional | `small`\|`medium`\|`large` — a prediction, not a limit |
| `checklist` | required, Atlas-native only | see §3 |
| `checkpoint` | required, Atlas-native only | see §3 |

**Derived, never stored:** progress percentage (from checklist state), the active set
(every ticket with `state: active`), which ticket a session concerns (resolved from cwd or
asked, never a stored pointer).

**Historical compatibility:** a historical ticket keeps `opened`/`updated` (date-only) and
carries no `kind`/`namespace`/`checklist`/`checkpoint` — none of this is retrofitted onto it.
`required_fields_for(id)` in `cli/atlas_tickets.py` already picks the right pair per
generation; this draft only writes down the rule the code enforces.

## 3. Metadata ordering

```text
1. identity           (kind, namespace, id)
2. title/description  (title)
3. lifecycle/state     (state)
4. project ownership   (project)
5. timestamps          (opened_at, updated_at)
6. supporting/static   (artifacts, class, expected_context)
7. checklist
8. checkpoint
```

Structural rule, Atlas-native only: `checklist → checkpoint → end of frontmatter`. Nothing
follows `checkpoint`. This exists so the record visually separates what the ticket **is**
(1–6) from where execution currently **stands** (7–8).

### Checklist contract

```yaml
checklist:
  - "[ ] pending item"
  - "[x] complete item"
```

- `[ ]` pending, `[x]` complete — no other marker.
- Meaningful completion criteria only; not a shell-command transcript.
- `state: done` must not coexist with any unchecked required item.
- Progress is derived from checklist state, never stored as a separate percentage field.

### Checkpoint contract

```yaml
checkpoint:
  current: completed
  updated_at: 2026-09-05 2:46 PM
```

- Only the **current** checkpoint lives in frontmatter — one value, not a trail.
- Checkpoint history stays in `## Log` (the existing append-only mechanism); this block is
  never a second log.
- `current: completed` is the value for a finished ticket; otherwise a short (one-line)
  description of the present boundary — never prose, never an execution transcript.

## 4. Time contract

Atlas-native tickets use a human-readable local timestamp:

```text
YYYY-MM-DD h:mm AM/PM        e.g. 2026-09-05 2:46 PM
```

- This is a **display/storage format for ticket metadata**, chosen for a human reading the
  record cold. It is not a statement about internal runtime timestamps (run ids, log lines
  elsewhere) which may use a machine-native form (ISO-8601, epoch) where that already
  applies — this draft does not redesign that.
- Resolved dynamically from the workspace/system clock at write time. No timezone is
  stored per ticket.
- Workspace default: `internal/config/settings.yaml` → `timezone: auto`. An explicit
  override at that same level is allowed; a per-ticket override is not introduced by this
  draft because nothing today needs one.
- `opened_at` is written once and never changes. `updated_at` changes only when the
  authoritative record is materially updated (a checkpoint, a state change, a log entry) —
  never on a read, never on an unrelated file touch.

Historical tickets keep plain `YYYY-MM-DD` dates (`opened`/`updated`) — not rewritten
retroactively to the new form; see §2.

## 5. States (unchanged)

```text
todo ──▶ active ──▶ done ──▶ (archive/)
          │  ▲
          │  └──── paused
          ├──────▶ blocked
          └──────▶ cancelled
```

Both generations share one state model. This draft does not touch it.

## 6. Compatibility

A historical `AIOS-*` ticket is valid, readable and complete exactly as it is today:
`opened`/`updated` dates, no `kind`/`namespace`, no `checklist`/`checkpoint`. Nothing in
this draft requires, schedules, or implies a retroactive rewrite of any existing ticket.
Doctor enforces this split already (`required_fields_for`, `atlas_metadata_issues` — the
latter checked for `T-*` ids only).
