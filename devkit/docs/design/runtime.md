# Runtime

Two different things have been called "runtime" in this system's history, and the name
collision is the most common source of confusion in older material. This document exists
to keep them separate.

## The retired runtime layer

Earlier versions of Atlas had a third layer, a directory at `~/.ai`, which held the live
hooks, the operational scripts, and the client integration that made the system actually
run. That layer is retired. Its engine became this repository's `cli/`, its client
integration became `adapters/<client>/`, the user's own data moved into the private
workspace, and its transient state lives under `$ATLAS_HOME/runtime/` — the second thing this
document is about. `atlas doctor` treats `~/.ai` as a legacy location and fails if it
still holds active components. Full history: `docs/design/public-private.md`.

## `$ATLAS_HOME/runtime/` — a directory, not a layer

`runtime/` is a directory *inside* the private workspace, owned by the workspace like
everything else under `$ATLAS_HOME`. It is not a third layer with an owner of its own —
see `docs/design/public-private.md` for the two-layer model this fits into.

It holds **transient generated state**: the `runtime` ownership class in that same
document — execution state that "may be discarded freely," as opposed to `system-default`
(seeded, never overwritten), `user-owned` (never touched), or `generated` (derived and
reproducible, regenerable by the tool that owns it). A Run's own bookkeeping
(`schemas/run.schema.md`) is the clearest example: a Run may carry a task id as an opaque
reference, but its execution state lives entirely in `runtime/`, and the two are never
merged.

## What this means in practice

Nothing under `runtime/` should be treated as a record worth keeping. If something there
turns out to matter beyond one execution, that is a sign it belongs in `$ATLAS_HOME/runtime/sessions/`,
`personal/knowledge/`, or a task record instead — not a reason to stop discarding
`runtime/` freely.
