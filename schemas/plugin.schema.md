# Capability (plugin) contract — version 1

An AI-OS **plugin** is a capability: something AI-OS can *do*. It answers
*"what can AI-OS do?"* — never *"how does this client reach AI-OS?"*, which is an
**adapter** (`schemas/adapter.schema.md`).

> Until 2026-08-31 this filename described client adapters. The two meanings had inverted;
> the inversion was recorded as deferred in `AIOS-001/checkpoint.md` §13.1 and resolved by
> task AIOS-005. `plugins/` now holds capabilities, `adapters/` holds client integrations.

**Core owns the mechanism; the capability owns the domain.** Core understands
`capability · availability · authority · invocation · result · verification · persistence`
and nothing else. It must never learn what a PRD is, what a browser engine is, or what a
deployment provider is. Those belong inside a capability and stay there.

## Status

**No capability ships today, and `plugins/` is empty by design.** This contract exists so
the first one has a shape to satisfy — not as a promise that one is coming. Discovery and
validation are implemented (`ai-os plugin list|doctor`). **Invocation is deliberately not
wired**: an invoke path with no capability to invoke would be machinery nothing consumes,
which is the defect this repository has already refused once (`ai-os adapter enable`).

## File

One manifest per capability: `plugins/<id>/plugin.yaml`.

```yaml
plugin: github                 # stable id — MUST equal the directory name
name: GitHub                   # human label
contract: 1                    # the capability contract version this manifest targets

capability:
  detect: [...]                # any path present => available on this machine (optional)
  authority: propose           # the HIGHEST rung any operation here may request

requires: [browser, filesystem]  # other capabilities this one needs. Optional.

operations:
  pull_request:
    summary: open a pull request
    command: run-pull-request  # a bare filename inside plugins/<id>/ — never a path
    authority: propose         # may not exceed capability.authority
    idempotent: false          # may a failed run be retried automatically? Default false.
    verify: check-pull-request # a bare filename; exit 0 = verified. Optional.
```

### Layout

The manifest parser is the one `cli/ai-os-adapter` owns — one parser, not two. A flow
collection may sit on its key's line or on the line(s) below it, because a code formatter
moves it and the document is unchanged either way; a collection that never closes is still
an error. See **Layout** in `schemas/adapter.schema.md`, and `.prettierignore`.

## Domains are not capabilities

A **domain** is an area of work that names outcome kinds and requires capabilities
(`schemas/domain.schema.md`, `domains/`). A capability is something AI-OS can *do*. The
arrow runs `Domain → requires → Capability` and never the reverse: a capability is never
owned by, scoped to, or a member of a domain, and **it declares no domain of its own**.

> A `capability.domain:` field existed here until 2026-09-01 as a free-form label. Core
> never read it, nothing validated it, and exactly one manifest set it — so when Domain
> became a real concept the field was **removed rather than renamed**, leaving one meaning
> for the word instead of two. Nothing consumed it, so nothing had to migrate.

## Idempotency and retry

`idempotent:` answers one question: **may this operation be retried automatically after a
failure?** It defaults to `false`, because the safe default for "may I do this again
without asking" is no.

```
idempotent: true    reading, navigating, observing   -> bounded automatic retry allowed
idempotent: false   submitting, purchasing, deleting -> never retried automatically
```

An operation that changes the world outside AI-OS is not idempotent, and a runner that
retries one is the most dangerous thing this contract can permit. The field exists so that
the answer is declared by the capability author rather than guessed by a caller.

## Dependencies

`requires:` names other capabilities by id — nothing else. It is how one capability reaches
another:

```yaml
plugin: github
requires: [browser, terminal, filesystem]
```

That is the whole mechanism. **There is no resolver**, no version range, no install
order, and no transitive graph — none of those has a use yet, and a dependency graph with
one capability in it is a graph nobody needs.

What is checked, deterministically:

| Rule | Verdict |
|---|---|
| `requires:` is a list of strings | error if not |
| each id matches `^[a-z0-9][a-z0-9-]*$` | error if not |
| an id contains `/`, `.` or `..` | **error** — a dependency names a capability, never a path |
| a capability requires itself | error |
| a required capability is not present in the registry | **warning**, not error |

The last row is deliberate. A capability may legitimately be declared before the thing it
needs is installed, so an unsatisfied dependency is reported and left visible rather than
failing the manifest — the same treatment `verified: false` already gets. What must never
happen is a dependency that silently resolves to a filesystem path.

## Five states that are not the same state

The whole point of the contract is that these never collapse into one boolean:

```
available    the capability exists and its detect: paths are present
allowed      policy permits the requested authority rung
invocable    available AND allowed AND the command file exists and is executable
executed     the command ran and returned a structured result
verified     a deterministic check confirmed the result — or none was claimed
```

`available` never implies `allowed`. `allowed` never implies `executed`. **`executed`
never implies `verified`** — that is the rule the whole contract exists to enforce.

## Authority

Every operation declares the rung it needs. The ladder is fixed:

```
observe  ->  propose  ->  execute  ->  execute-with-approval  ->  autonomous
```

An operation may never exceed its capability's `authority:`, and a capability may never
exceed what policy grants. **`autonomous` is not implementable today** — nothing grants it,
and a manifest requesting it is rejected rather than silently downgraded. Recording the
rung now is what keeps a future automation layer from arriving as an `--auto` flag.

## Verification

`verify:` names a deterministic check. It is the mechanism that stops a capability
reporting its own success:

```
invoke  ->  structured result  ->  verify (exit 0 = verified)  ->  verified | failed
```

A capability with **no** `verify:` is valid — but its result is `executed`, never
`verified`, and core must report it that way. A model asserting success is not
verification and must never be recorded as one.

## What a capability may not do

- **Name a client.** No capability may contain `claude`, `codex`, `cursor`, `gemini` or
  `opencode`. Client integration is an adapter's job. This is mechanically checked.
- **Reach into `$AI_OS_HOME`.** A `command:` is a bare filename inside its own
  `plugins/<id>/` directory — never a path, never an escape. Also checked.
- **Invent an authority rung.** The five above are the whole ladder.
- **Declare itself verified.** Only a `verify:` command's exit status does that.

## Contract versioning

A manifest declaring `contract: 2` on a core supporting `1..1` is **disabled with an
explicit reason**, never partially honoured — the same rule the adapter contract uses.
