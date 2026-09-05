# Adapter contract — version 1

An AI-OS **adapter** connects **one AI client** to AI-OS. It is code. `$AI_OS_HOME` is the
user's data. The contract exists to keep those two facts from blurring.

> **Core resolves. Adapters integrate.**
> An adapter never owns, never declares, and never reaches into `$AI_OS_HOME` on its own.

**An adapter is not a capability.** An adapter answers *"how does this client reach
AI-OS?"*; a capability answers *"what can AI-OS do?"*. Capabilities live in
`capabilities/` and are described by `schemas/capability.schema.md`. Until 2026-08-31 this
file was named `plugin.schema.md` and `adapters/` manifests lived in `plugins/` — the
inversion recorded as deferred in `AIOS-001/checkpoint.md` §13.1, resolved by task
AIOS-005. The capability surface was then renamed `plugin` -> `capability` on 2026-09-03;
that rename changed no adapter semantics.

This schema describes what five already-installed clients do today. It was derived from
observed configuration, not designed in advance — `~/.ai/capabilities.yaml` had been
recording exactly this since 2026-08-30, and this file promotes that record from
documentation into a checkable contract.

## File

One manifest per adapter: `adapters/<id>/adapter.yaml`.

```yaml
adapter: claude-code       # stable id — MUST equal the directory name
name: Claude Code          # human label
contract: 1                # the AI-OS adapter contract version this manifest targets

client:
  detect: [~/.local/bin/claude, ~/.claude/]   # any path present ⇒ client installed
  version_cmd: claude --version               # optional; version is OBSERVED, never declared
  consumer_verified: true                     # see below

provides: { ... }          # surfaces this adapter can write, in ITS client's domain
requires: [ ... ]          # core resources it needs; core resolves these
enforces: [ ... ]          # core policies this adapter implements
```

### Layout

`cli/ai-os-adapter` reads this subset with a hand-written parser, not pyyaml — AI-OS has
no dependencies. It rejects what it cannot read rather than guessing, because a silently
mis-parsed manifest is worse than an unreadable one. `cli/ai-os-capability` and
`cli/ai-os-domain` borrow the same parser, so this holds for every manifest in the repo.

A flow collection may sit on its key's line or on the line(s) below it. These are the same
manifest, and both parse:

```yaml
provides: { rules: { path: ~/.claude/CLAUDE.md, format: markdown, verified: true } }
```

```yaml
provides:
  { rules: { path: ~/.claude/CLAUDE.md, format: markdown, verified: true } }
```

The second form is what a code formatter produces, and one did — silently breaking every
tool that resolves clients from the registry. Reading both costs nothing and removes a
whole class of breakage. Strictness is unchanged otherwise: a collection that never
closes, or trailing content after one, is still an error with a reason.

Formatters should leave this repository alone regardless — see `.prettierignore`.

## Lifecycle — exactly three verbs

```
detect()        is this client present on this machine?
apply(bundle)   render core's bundle into this client's own config domain
doctor()        report this adapter's health; change nothing
```

Nothing else. `install`, `uninstall`, `enable`, `disable` and `status` are **core registry
operations**, not adapter behaviour:

- installing = placing files core already has → core's job
- enable/disable = a boolean in the registry → core's job
- status = derivable from `detect()` + `doctor()` + registry state → a fourth verb that
  returns only what three already know is surface without capability

`rollback` is deliberately absent: core backs up by timestamp tag and restores every
client at once. Per-adapter rollback would fragment a mechanism that already works.

## Capabilities

Every entry under `provides:` declares three fields. All three are required.

```yaml
provides:
  rules:  { path: ~/.claude/CLAUDE.md, format: markdown, verified: true }
  skills: { path: ~/.claude/skills/, format: SKILL.md+frontmatter, verified: true }
```

| Field | Meaning |
|---|---|
| `path` | where this capability is written, in the client's own domain |
| `format` | what is written there |
| `verified` | **has this path been confirmed by evidence?** |

**`verified: false` ⇒ core MUST NOT write that capability.** Not "should warn" — must not.
Evidence means a file the client itself created, the client's documented config schema, or
a published standard. A guess is not evidence, and writing to a guessed path is worse than
having a gap: it produces a file the client never reads and a user who believes it works.

`verified: partial` is treated as `false` for writing. It records that something was
observed without being confirmed writable.

### `consumer_verified`

Separate from, and weaker than, `verified`. `verified` says *we know where the file goes*.
`consumer_verified` says *we have observed the client actually reading it*. A client can
have a fully verified path and still be unverified as a consumer — Codex created an empty
`AGENTS.md` itself, which proves it knows the path, not that it reads what we put there.

Only `consumer_verified: true` may be described as behaviourally supported.

## Path ownership — the hard rule

An adapter may declare `provides:` paths **only inside its own client's configuration
domain**:

```
~/.claude/   ~/.codex/   ~/.gemini/   ~/.cursor/   ~/.config/opencode/
```

It may **never** declare a path under `$AI_OS_HOME`. `ai-os doctor` rejects any manifest
whose `provides:` path resolves inside the private workspace — a hard failure, not a
warning. This is mechanically checkable, so it is checked.

When an adapter needs workspace data it asks, and core resolves:

```yaml
requires:
  - rules.render            # the rendered canonical rules bundle
  - skills.list             # the resolved skill set (user skills shadow public ones)
  - workspace.memory.path   # a resolved path — a grant, not a filesystem license
```

## Integration points

`provides:` covers what core **writes into** a client. Some core capabilities instead need
one fact only the client's own adapter can supply. Those are declared under `integrates:`:

```yaml
integrates:
  memory.mounts: { command: ai-memory-mounts, format: newline-paths, verified: true }
```

| Field | Meaning |
|---|---|
| `command` | a bare filename inside `adapters/<id>/` — never a path |
| `format` | the contract of what it prints on stdout |
| `verified` | same rule as `provides`: **not `true` ⇒ core MUST NOT call it** |

**Core defines the integration points; an adapter may never invent one.** An unrecognized key
under `integrates:` is a hard failure, exactly like an unknown `requires:` resource. The
point exists so core keeps the mechanism and the adapter keeps only its client's facts:

```
memory.mounts   adapter answers "where does my client keep memory directories?"
                core decides what a healthy mount is, attaches it, and rescues
                anything already there — for every client, identically
```

This is what lets one memory engine serve every client without a fork. Nothing in
`cli/ai-os-memory` names a client, and any adapter that declares `memory.mounts` gets the
whole engine. Today only `claude-code` declares it, because only Claude Code scopes memory
by working directory — that is a fact about Claude Code, not a shape in core.

### The honest limitation

`workspace.memory.path` is a real filesystem grant. Claude Code's native memory tool opens
and writes files itself; no wrapper can intermediate it. What the contract guarantees is
that the grant is **declared in the manifest, scoped to one subtree, and listed by
`doctor`** — visible, not invisible. Claiming more would be the kind of faked compatibility
this schema exists to prevent. Narrowing it to per-project scope needs the memory schema
and belongs to V0.2.

## Enforcement

```yaml
enforces: [git]     # implements internal/governance/policies/git.yaml in this client's mechanism
```

An adapter *implements* a policy. It never restates one, never relaxes one, and never
defines its own. The policy lives in `internal/governance/policies/`, client-agnostic; the adapter is one
enforcement of it.

## Compatibility

Three versions move independently:

```
Core       0.1.x    supports a contract RANGE
Contract   1        this schema
Workspace  1        the ~/.ai-os layout
```

An adapter declaring `contract: 2` on a core supporting `1..1` is **disabled with an explicit
reason**. It is never partially applied — a half-written `CLAUDE.md` is worse than none —
and never silently upgraded, downgraded, or disabled. Breaking changes to this schema
increment `contract`, and nothing else does.
