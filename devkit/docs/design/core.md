# Core

**Core resolves. Adapters integrate.** Core is the mechanism Atlas shares across every
client and every capability — the part that must never learn what a PRD is, what a
browser engine is, or how one specific client's config format works. Those belong to a
capability or an adapter, and stay there.

## What Core owns

Exactly seven concepts, and nothing else:

```
capability · availability · authority · invocation · result · verification · persistence
```

Everything in the adapter, capability, domain and run contracts (`schemas/`) is Core
enforcing one of these seven consistently, regardless of which client or which capability
is involved. A capability owns its *domain* (what a browser operation actually does); Core
owns the *mechanism* around it (whether it's available, whether policy allows it, whether
the result was verified).

## Where Core actually lives today

There is no separate, executable Core directory. Core is implemented across `cli/` —
one entry point, `atlas`, dispatching to `atlas-adapter`, `atlas-capability`, `atlas-domain`,
`atlas-run`, `atlas-memory`, `atlas-doctor` and the rest — and specified by `schemas/`.
`internal/core/README.md` exists only as a pointer to this document, because the concept and the
implementation are not yet in the same place, and pretending otherwise would be exactly
the kind of stale claim `AGENTS.md` warns against.

## The rule this produces

An adapter never reaches into `$ATLAS_HOME` itself; it asks Core for a resolved path or a
rendered bundle. A capability never learns a client's name; Core's discovery and
invocation path is the only thing that touches both a capability and an adapter in the
same call. This is what keeps adding a sixth adapter, or a second capability, from
requiring changes to the other four adapters or the first capability — each side only
ever talks to Core.

## Read next

- `../use/adapters.md`, `../use/capabilities.md`, `../use/domains.md` — the three
  things Core mediates between.
- `governance.md` — how policy constrains what Core is allowed to do.
- `domain-delivery.md` — why a domain declaration stops at "requires
  capabilities" instead of becoming a fourth thing Core executes.
