# Capabilities — what Atlas can do

A **capability** answers *"what can Atlas do?"* — the kind of thing browser control,
software delivery or automation would each be. Its contract is
`../schemas/capability.schema.md`.

## What ships today

| Capability | Directory | Operations |
|---|---|---|
| `browser` | `browser/` | fourteen, driving a real browser — open · close · navigate · read · observe · extract · click · type · select · scroll · wait · upload · download · submit |

One real capability, not a set of placeholders. `browser` declares
`authority: execute-with-approval` as its **ceiling**, not its normal rung: reads and
observations sit at `observe`, ordinary interaction at `execute`, and only the three
operations that change the world irreversibly — upload, download, submit — actually
require approval. Its provider is selected at runtime and named nowhere in the manifest,
so the browser engine is replaceable without touching the capability or Core.

Every operation is checked by `browser-verify`, which re-reads live browser state rather
than trusting the operation's own report. That is why *executed* and *verified* are
separate outcomes, and why the operations that change something outside Atlas are
`idempotent: false` and never retried automatically.

## Capability, adapter, domain

An **adapter** answers *"how does an AI client reach Atlas?"* — Claude Code, Codex,
Cursor, Gemini, OpenCode. Those live in `../adapters/`, contract
`../schemas/adapter.schema.md`. A capability is client-agnostic and never names one.

```
client  ->  adapter  ->  Atlas Core  ->  capability  ->  execution  ->  verification
```

A **domain** (`../domains/`) names an area of work and the capability **ids** that
delivering its outcomes would need. A domain is inert: no command, no verifier, no
provider, no authority rung, no ordering. Nothing executes a domain — declaring one is
the whole feature. Contract: `../schemas/domain.schema.md`.

This directory once held the client manifests, which are adapters. That inversion is
resolved: `../adapters/` holds clients, this directory holds capabilities, and no prose
in this repository should use `plugin` to mean an adapter.

## The `plugin` -> `capability` rename, and what still works

This directory was `plugins/` until 2026-09-03, and the whole surface was spelled
`plugin`. The current name is `capability`. Every old spelling still works for one
version, and each is compatibility only — not a second supported way of doing things:

| | Current | Compatibility |
|---|---|---|
| directory | `capabilities/` | `plugins/`, still read if pointed at |
| manifest file | `capability.yaml` | `plugin.yaml`, still accepted |
| CLI | `atlas capability` | `atlas plugin`, an alias |
| env var | `ATLAS_CAPABILITIES` | `ATLAS_PLUGINS`, a fallback |
| **manifest key** | **`plugin:`** | unchanged — renaming it is a contract 2 change |

The manifest key is the deliberate exception: `capability:` is already the authority block
inside a manifest, so reusing that word for the id would give it two meanings in one
document. A manifest written for contract 1 needs no edit.

Both filenames in one directory with **differing** content is reported as a conflict and
never merged; identical content resolves to `capability.yaml`.

The rename changed names only. Domain declarations, adapter manifests, the authority
ladder and the execution path are all exactly as they were.
