# Capabilities

A **capability** answers *"what can Atlas do?"* — the kind of thing browser control,
software delivery or automation would each be. It is not an adapter — an adapter answers
*"how does this client reach Atlas?"* (`docs/use/adapters.md`). Capabilities live in
`capabilities/`, are client-agnostic, and are reached by every client through its adapter;
there is never a per-client copy of one. Full contract: `schemas/capability.schema.md`.
Living inventory: `capabilities/README.md`.

## What ships today

One capability: `browser`, in `capabilities/browser/` — real browser control, fourteen
operations (open, close, navigate, read, observe, extract, click, type, select, scroll,
wait, upload, download, submit).

## If you knew this as `plugin`

It was called that until 2026-09-03. The old spellings still work for one version, and are
compatibility only:

| | Current | Compatibility |
|---|---|---|
| directory | `capabilities/` | `plugins/` |
| manifest file | `capability.yaml` | `plugin.yaml` |
| command | `atlas capability` | `atlas plugin` |
| env var | `ATLAS_CAPABILITIES` | `ATLAS_PLUGINS` |
| **manifest key** | **`plugin:`** | unchanged — a contract 1 manifest needs no edit |

The manifest key stays `plugin:` because `capability:` already names the authority block
inside a manifest; changing it belongs to a contract 2 that does not exist. If both
manifest filenames are present and their content differs, that is reported as a conflict —
nothing is merged. The rename changed names only: domains, adapters and the execution path
are untouched.

## Five states that don't collapse into one boolean

```
available    the capability exists and its detect: conditions are present
allowed      policy permits the requested authority rung
invocable    available AND allowed AND the command file exists and is executable
executed     the command ran and returned a structured result
verified     a deterministic check confirmed the result — or none was claimed
```

**`executed` never implies `verified`.** A capability with no `verify:` step is valid, but
its result is reported as `executed`, never `verified` — a model asserting success is not
verification.

## Authority is a ceiling, not a default

Each capability declares the *highest* rung any of its operations may request:

```
observe  ->  propose  ->  execute  ->  execute-with-approval  ->  autonomous
```

`browser` declares `execute-with-approval` as its ceiling, but most of its operations sit
lower: reads and observations at `observe`, ordinary interaction at `execute`. Only the
operations that change the world irreversibly — upload, download, submit — actually
require approval. `autonomous` is not implementable today; a manifest requesting it is
rejected, not silently downgraded.

## Idempotency

`idempotent:` answers one question: may this operation be retried automatically after a
failure? It defaults to `false`. Reading, navigating and observing can be `true`;
submitting, purchasing and deleting are never retried automatically.

## Commands

```bash
atlas capability list
atlas capability doctor
atlas capability invoke browser.read --dry-run
```

`invoke` runs **one** declared operation and stops, walking `available -> allowed ->
invocable -> executed -> verified` and refusing at whichever arrow fails. Nothing in this
repository chains those calls into a plan, a workflow or an agent loop — that boundary is
the point, not a gap. `--dry-run` reports whether an operation *would* be invocable
without executing it.
