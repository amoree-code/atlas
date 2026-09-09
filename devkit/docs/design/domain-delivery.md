# Domain Delivery

**You can declare an area of work. Nothing will run it. Declaring is the feature.**

This document is the design rationale behind `docs/use/domains.md` and
`schemas/domain.schema.md`. It exists because "why doesn't a domain do anything" is the
first question anyone asks, and the honest answer is a deliberate one, not a gap waiting
to be filled.

## Three levels that never collapse

| Level | Example | Lives in |
|---|---|---|
| Domain | `software` | `domains/software.yaml` |
| Outcome **kind** | `mobile-app` | the declaration, as vocabulary |
| Outcome **instance** | a particular mapping app, for a particular client | a task in the private workspace |

A domain names the vocabulary for an area of work. An outcome kind is a word in that
vocabulary. An outcome instance is a real, specific thing someone is actually trying to
deliver — and that instance is never written into the public declaration, because a
declaration is public software and an instance is somebody's actual work.

## The one legal direction

```
Domain  → requires →  Capability          the only legal direction
Capability → belongs to → Domain          forbidden — that is ownership
```

A domain *uses* capabilities by naming their ids under `requires:`. It never owns,
contains, scopes or reimplements one, and a capability declares no domain of its own — a
`capability.domain:` field existed briefly and was removed rather than renamed once Domain
became a real concept, because nothing had ever read it.

## Why a domain is inert on purpose

A declaration able to express sequence, or map an outcome onto a specific capability
operation, would be a workflow engine under another filename. So neither is expressible:
the schema refuses `stages`, `steps`, `then`, `order`, `sequence`, `depends_on`,
`workflow`, `dispatch`, `command`, `provider`, `verify` and `authority` **by name**, with a
reason attached to each, rather than leaving them merely undocumented. Execution stays
`Task + Capability + Run + Verification`, unchanged — a domain adds vocabulary to that,
nothing else.

This is the same restraint documented in `docs/design/decisions.md`: an abstraction with
no working code behind it is worse than not having the abstraction yet, and an execution
engine for domains has no working code behind it today.

## What Core may not do

Core validates the *shape* of a domain declaration and never interprets its *meaning* —
there is no branch anywhere in the domain command on a specific domain id or outcome name.
This is what makes a domain additive: adding one must never require editing Core. A second,
unrelated domain existing alongside the first is the proof this holds, not an assertion
that it does.

## Read next

`docs/use/domains.md` for the practical shape and commands. `schemas/domain.schema.md` for
the full, versioned contract, including every refused key and why.
