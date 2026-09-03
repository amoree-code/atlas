# Domain contract — version 1

A **domain** is an area of work. It names the outcome kinds that area recognizes, and the
capabilities that delivering them needs. It answers *"what result are we trying to
accomplish, and what would that need?"* — never *"what can AI-OS do?"*, which is a
**capability** (`schemas/capability.schema.md`), and never *"how does a client reach AI-OS?"*,
which is an **adapter** (`schemas/adapter.schema.md`).

```
Domain  → requires →  Capability          the only legal direction
Capability → belongs to → Domain          forbidden — that is ownership
```

A domain *uses* capabilities. It never owns, contains, scopes or reimplements one, and a
capability declares no domain of its own.

## A domain is inert

This is the whole contract in one line. A declaration has **no command, no verifier, no
provider, no authority rung, and no ordering.** Nothing about a domain executes, and there
is deliberately no verb that could: `ai-os domain` has exactly `list` and `doctor`, both
read-only.

Execution stays `Task + Capability + Run + Verification`, unchanged. A declaration able to
express sequence, or to map an outcome onto an operation, would be a workflow engine under
another filename — so neither is expressible here, and the validator refuses both by name.

## File

One flat file per domain: `domains/<id>.yaml`. The id **MUST** equal the filename stem.

Flat rather than `domains/<id>/domain.yaml` on purpose. Capabilities and adapters get a
directory because they hold executables; a domain holds none, and a directory would invite
one. The layout does the enforcing.

```yaml
domain: software        # stable id — MUST equal the filename stem
name: Software          # human label
contract: 1             # the domain contract version this declaration targets

requires: [browser]     # capability ids this domain needs. Optional.

outcomes:               # outcome KINDS — a set, never a sequence
  mobile-app:
    summary: a mobile application built, packaged and released
```

## Exactly five fields

`domain` · `name` · `contract` · `requires` · `outcomes`. Any other key is an error.

The allowlist is the mechanism. Enumerating in prose what an author must not write is
advice; refusing every key that is not one of five is a guarantee — and it catches the bad
idea that has not been thought of yet. Keys that are a rejected concept are refused *by
name*, with the reason:

| Key | Refused because |
|---|---|
| `authority` | a domain grants nothing — authority is declared by a capability and granted in `internal/config/authority.yaml` |
| `verify` | a domain defines no verifiers — verification is a capability operation's own `verify:`, and `executed` never implies `verified` |
| `command` · `provider` | a domain is inert; it has no executable of its own |
| `detect` | availability is a capability property — a domain is not installed |
| `operations` | operations belong to a capability; a domain names outcome kinds |
| `stages` · `steps` · `then` · `order` · `ordering` · `sequence` · `depends_on` · `workflow` | outcomes are a set, never a sequence |
| `dispatch` | nothing maps an outcome onto an operation — the model decides that, and a table here would be a planner |
| `run` | a domain is never bound to a Run; a Run carries a task id and nothing else |
| `task` | a domain declares no task fields — task state is convention-only and Core never parses it |

`domain`, `name`, `contract` and `outcomes` are required. `requires:` is optional — a
domain that needs no capability is legitimate.

## Outcome kinds, and outcome instances

`outcomes:` is a map of **kinds** — vocabulary. Each kind is a name and a `summary`, and
nothing else.

An outcome **instance** is a particular result being pursued: a specific app, for a
specific client, this quarter. It is named by a task in the private workspace and lives
with that task. **It never appears in a declaration.** The three levels never collapse:

| Level | Example | Lives in |
|---|---|---|
| Domain | `software` | `domains/software.yaml` |
| Outcome **kind** | `mobile-app` | the declaration |
| Outcome **instance** | a particular mapping app | `tasks/<ID>/task.md` |

## Dependencies

`requires:` names capabilities by id — nothing else. It is the same mechanism, with the
same five rules, that the capability contract already uses. **There is no resolver**, no
version range, no install order and no transitive graph.

| Rule | Verdict |
|---|---|
| `requires:` is a list of strings | error if not |
| each id matches `^[a-z0-9][a-z0-9-]*$` | error if not |
| an id contains `/`, `.` or `..` | **error** — a dependency names a capability, never a path |
| a domain requires itself | error — and a domain is not a capability |
| a required capability is not in the registry | **warning**, not error |

The last row is deliberate, and identical to the capability contract's reasoning: declaring
a domain before its capabilities are installed is legitimate, so an unsatisfied requirement
stays visible rather than fatal.

## What a domain may not do

- **Execute anything.** There is no verb, no command, and no code path that runs.
- **Name a client.** No declaration may contain a client's name — client integration is an
  adapter's job. Mechanically checked, exactly as it is for a capability.
- **Grant authority, or verify its own outcomes.** Both belong elsewhere and stay there.
- **Order its outcomes**, or map one onto a capability operation.

## What Core may not do

Core validates the **shape** of a declaration and never interprets its **meaning**. There
is no branch anywhere in `cli/ai-os-domain` on a domain id or an outcome name — asserted by
test, as an absence.

This is what makes a domain additive: **adding one must not require editing Core.** The
suite proves it in both directions — a domain core has never heard of, declaring an outcome
core has never heard of, validates exactly like a declared one; and a second, unrelated
domain was added without a line of CLI logic changing.

## Contract versioning

There is one version of this contract. A declaration targeting an unsupported version is
**disabled with an explicit reason**, never partially honoured — the same rule the adapter,
capability and run contracts use.
