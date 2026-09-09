# Agentic preflight contract — version 1

Preflight is the deterministic gate between an Agentic packet and any coordinator,
adapter, or transport call. It checks bounds already supplied by the caller; it does not
choose a model, infer a provider, estimate a price from a model name, or invoke a client.

## Required inputs

```json
{
  "packet": "runtime/packets/<run_id>/<packet_id>.json",
  "estimated_cost_usd": 0.07,
  "cost_limit_usd": 0.25,
  "transport_verified": true,
  "unresolved": false
}
```

The packet must pass the existing context-packet contract. Its `root.ticket` must match
the Agentic run's ticket and its `root.scope` must match the run's exact claim. The packet's
own `budget.used` and `budget.limit` are the token values checked here.

`budget.used` may be measured provider usage or a labelled character proxy. A proxy is
never presented as measured usage. `estimated_cost_usd` must come from a declared pricing
source; preflight never derives it from a client or model name.

## Decisions

| Decision | Meaning |
|---|---|
| `CONTINUE` | packet is below the token and cost limits and the transport is verified |
| `COMPACT` | packet is at or above 80% of its token limit and must be reduced first |
| `BLOCKED` | a limit, transport, or unresolved-context guard failed |

The checks are fail-closed. An unverified transport, unresolved context, token overflow,
or cost overflow cannot continue. Preflight is read-only in this slice; it writes no run,
mission, handoff, ticket, or client state.

## Ownership

- `agentic` owns when preflight runs and whether its decision permits the next stage.
- `context` owns packet construction and context selection.
- `coordinator` owns role and handoff routing.
- `adapter` and `transport` registries own client delivery declarations.
- `usage` owns post-run measured usage and actual cost.

No second authority ledger or model-routing gateway is introduced.

## Post-run reconciliation

`atlas agentic reconcile` consumes a provider-neutral JSON usage report produced by the
existing usage layer. It persists measured token totals and an optional actual dollar cost
under the Agentic run record. Missing dollar data is `unreported`, never estimated from
weighted tokens. A reconciliation is write-once; it cannot overwrite earlier evidence.

`atlas coordinator dispatch` may supply the Agentic run and packet references. When it does,
dispatch runs this preflight immediately before the existing send call and refuses any
non-`CONTINUE` result. The legacy dispatch path remains available when no Agentic preflight
tuple is supplied; it retains its existing approval, lease, claim, and transport gates.
