# Handoff contract — draft

```text
Status:    DRAFT
Authority: non-canonical during Phase A
Current live contract remains under internal/templates/agent-handoff.md and the actual
cli/ai-os-handoff behavior. Promotion requires a later migration slice.
```

Context loading: load only when preparing, approving, sending or reviewing a handoff. Not
always-on.

## Current source(s)

- `internal/templates/agent-handoff.md` — the manual, human-readable template in production.
- `cli/ai-os-handoff` — the real enforced gates (`plan-scope`, `execute`, `review`,
  `next-step`, `remote-or-destructive`, `resume`) and statuses (`draft`, `waiting-owner`,
  `returned`, `reviewed`, …).
- AIOS-010 (design), AIOS-011 (owner-approved implementation), AIOS-012 (low-cost CLI
  transport) — the decisions this draft does not redo.

## Future relationship

Candidate generalization of the current template into a structured contract once
`schemas/`→`contracts/` is promoted (Phase E). Field names below are chosen to match the
template's existing sections one-for-one where they already exist, so promotion is a
rename/typing pass, not a redesign.

---

## What this is (and is not)

> A durable, transportable **work record** — not an autonomous hidden agent-to-agent
> messaging bus.

Carried over unchanged from the current template:

- Not hidden agent-to-agent messaging — every handoff is a written record the owner can
  read, keep and inspect.
- Not a workflow engine, not an agent runtime, not agent orchestration. It describes work
  that already happened; it sequences, schedules and triggers nothing.

## 1. Durable identity/context

| Field | Required? | Notes |
|---|---|---|
| `handoff_id` | optional | a generated id only when uniqueness genuinely needs one (e.g. kept beside a ticket); an ordinary hand-pasted handoff needs none |
| `source ticket` (`task_id`) | optional | `SCOPE-###`/`T-###`, a backlog line, or `-` if neither exists. Kept as `task_id` on purpose — see §6 |
| `work/responsibility` | optional | only when a ticket is subdivided into separately handed-off pieces; **not forced** when the handoff is the whole ticket |
| `sender` (`planner_ai`/`executor_ai`) | required | client + model, or `owner` if unplanned |
| `receiver` (`reviewer_ai`) | optional | client + model, or `unassigned` |
| `objective` | required | what the owner actually asked for, in their terms |
| `allowed scope` (`allowed_files`) | required | every path the executor was permitted to change |
| `constraints` (`forbidden_scope`) | required | what was explicitly off limits |
| `evidence/results` | required | a path, a command and its output, a test result — never "looks fine" |
| `verification` | required | `run \| not run`, and if not run, why. `executed ≠ verified` |
| `unresolved` | required | what was not settled, honestly, even if the answer is "nothing" |
| `owner approval state` | optional | only present when the record is kept beside a ticket; see §4 |

Human-readable names are used above (`sender`, `receiver`, `objective`) because nothing
today needs a generated identifier to disambiguate them — a handoff is read by a person,
not resolved by machine lookup. `handoff_id` is the one field that gets a generated form,
and only when it will be referenced later (kept beside a ticket, or approved/sent through
the CLI's gate machinery).

## 2. Request vs result

Two shapes, kept distinct exactly as the current template already does:

**Handoff request** — §§1–2 of the template (metadata, original request): what the owner
asked for and what scope the executor was granted. Written before work starts.

**Handoff result** — the compact result packet (§9 of the template): what the receiving
side needs to decide and act, without the transcript that produced it.

| Field | Required? | Notes |
|---|---|---|
| `objective` | required | what this hop was asked to establish or change |
| `findings` | required | what is now known that was not known before — the answer, not the search |
| `evidence` | required | path, command+output, test result, run id — never "looks fine" |
| `confidence` | optional | `high\|medium\|low`, per finding where they differ |
| `paths` | required | the files/resources the next step will need, nothing else |
| `constraints` | required | what the next step must not do, and why |
| `recommendation` | required | the single next action, concrete enough to start cold |
| `unresolved` | required | what was not settled, and what would settle it |
| `verification` | required | `run \| not run`, and if not run, why |

`allowed_files`, `forbidden_actions`, `commands_allowed`, `expected_return`, and
`token_budget_hint` were historical proposals surveyed for this draft; none are carried
forward as required fields because none currently have a consumer beyond `allowed_files`
(already covered above as allowed scope) and `forbidden_scope` (already covered as
constraints). A field earns its place by having a reader — these did not.

## 3. No hidden bus

Restated because it is load-bearing, not decorative: this contract is a **durable,
transportable work record**. It is never an autonomous hidden agent-to-agent messaging bus
— nothing here dispatches, schedules, retries, or routes on its own. Every hop is a file a
person can open.

## 4. Owner approval

Unchanged from current policy: **a missing approval is a refusal.** Silence, the owner
being offline, and a previous approval are not approval. One approval covers one gate and
one scope; remote, destructive, credential, install, publish, push, delete and migration
actions always need their own line. An AI may write the request; only the owner grants it.
This draft does not redesign the approval architecture (`GATES` in `cli/ai-os-handoff`) —
it only names where approval state sits in the record.

## 5. Compatibility

The current template (`internal/templates/agent-handoff.md`) stays exactly as it is —
free text, nothing parses it, no schema validates it today. This draft does not require any
existing handoff record to be rewritten, and the current `ai-os handoff` CLI behavior
(gates, statuses) is unchanged by this ticket.

## 6. Naming note

`task_id` stays as the field name for "source ticket" — renaming it is a schema-breaking
change with no functional benefit (`naming-collisions.md` §task). It means *ticket* in this
one field, nothing else; "task" is not reintroduced as a folder or concept name.
