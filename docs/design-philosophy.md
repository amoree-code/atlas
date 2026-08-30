# Design philosophy

## Conceptual boundaries, kept distinct

```
Memory ≠ Knowledge
Skill ≠ Tool
Tool ≠ MCP
Agent ≠ Model
Model ≠ Client
Policy ≠ Permission
Session ≠ Task
Public Code ≠ User Data
```

Collapsing any of these pairs is where architectures like this one usually go wrong —
each is a genuinely different axis, and conflating two makes both harder to reason about.

## Principles

**Local-first.** User data stays local by default.

**Vendor-neutral.** The architecture is not built around any one model provider.

**Capability-based.** Think in what a component can do, not which brand made it.

**Modular.** Optional functionality is a module or adapter, not baked into the core.

**Safe autonomy.** The agent can act on its own, but sensitive operations — a remote
push, a merge, a delete — require explicit approval. See `../policies/`.

**Context-efficient.** Retrieve only what's relevant. Never load the whole workspace for
a request that needs three files.

**Persistent learning.** A result worth keeping becomes a compact knowledge entry, not a
transcript to re-read later.

**Human control.** The user is the authority over anything hard to reverse.

**Observable.** What the agent is doing should be legible, not opaque.

**Recoverable.** An operation can be rolled back or reasoned about after the fact.

**Simple for the user, not simple internally.** A user should understand seven folders:
`config/ memory/ knowledge/ projects/ sessions/ daily/ skills/`. They should not need to
understand an orchestrator, an event bus, or an adapter's internals to use the system.

## Why V0.1 is this small

It's tempting to build toward the full picture — an autonomous task engine, multi-agent
orchestration, a model router, a policy engine covering every action — in the first pass.
That produces abstractions with no working code behind them, which is worse than not
having the abstraction yet. V0.1's job is a foundation that's actually exercised: one
policy that already had a real implementation to migrate (git push approval), one working
adapter (Claude Code), and a workspace shape simple enough that a person can read it in
one sitting. Everything else is a later, deliberate version — not an oversight.
