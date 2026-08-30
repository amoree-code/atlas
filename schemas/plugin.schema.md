# Plugin contract — version 1

An AI-OS plugin adapts **one AI client** to AI-OS. It is code. `$AI_OS_HOME` is the
user's data. The contract exists to keep those two facts from blurring.

> **Core resolves. Plugins integrate.**
> A plugin never owns, never declares, and never reaches into `$AI_OS_HOME` on its own.

This schema describes what five already-installed clients do today. It was derived from
observed configuration, not designed in advance — `~/.ai/capabilities.yaml` had been
recording exactly this since 2026-08-30, and this file promotes that record from
documentation into a checkable contract.

## File

One manifest per plugin: `plugins/<id>/plugin.yaml`.

```yaml
plugin: claude-code        # stable id — MUST equal the directory name
name: Claude Code          # human label
contract: 1                # the AI-OS plugin contract version this manifest targets

client:
  detect: [~/.local/bin/claude, ~/.claude/]   # any path present ⇒ client installed
  version_cmd: claude --version               # optional; version is OBSERVED, never declared
  consumer_verified: true                     # see below

provides: { ... }          # capabilities this plugin can write, in ITS client's domain
requires: [ ... ]          # core resources it needs; core resolves these
enforces: [ ... ]          # core policies this plugin implements
```

## Lifecycle — exactly three verbs

```
detect()        is this client present on this machine?
apply(bundle)   render core's bundle into this client's own config domain
doctor()        report this plugin's health; change nothing
```

Nothing else. `install`, `uninstall`, `enable`, `disable` and `status` are **core registry
operations**, not plugin behaviour:

- installing = placing files core already has → core's job
- enable/disable = a boolean in the registry → core's job
- status = derivable from `detect()` + `doctor()` + registry state → a fourth verb that
  returns only what three already know is surface without capability

`rollback` is deliberately absent: core backs up by timestamp tag and restores every
client at once. Per-plugin rollback would fragment a mechanism that already works.

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

A plugin may declare `provides:` paths **only inside its own client's configuration
domain**:

```
~/.claude/   ~/.codex/   ~/.gemini/   ~/.cursor/   ~/.config/opencode/
```

It may **never** declare a path under `$AI_OS_HOME`. `ai-os doctor` rejects any manifest
whose `provides:` path resolves inside the private workspace — a hard failure, not a
warning. This is mechanically checkable, so it is checked.

When a plugin needs workspace data it asks, and core resolves:

```yaml
requires:
  - rules.render            # the rendered canonical rules bundle
  - skills.list             # the resolved skill set (user skills shadow public ones)
  - workspace.memory.path   # a resolved path — a grant, not a filesystem license
```

## Integration points

`provides:` covers what core **writes into** a client. Some core capabilities instead need
one fact only the client's own plugin can supply. Those are declared under `integrates:`:

```yaml
integrates:
  memory.mounts: { command: ai-memory-mounts, format: newline-paths, verified: true }
```

| Field | Meaning |
|---|---|
| `command` | a bare filename inside `adapters/<plugin>/` — never a path |
| `format` | the contract of what it prints on stdout |
| `verified` | same rule as `provides`: **not `true` ⇒ core MUST NOT call it** |

**Core defines the integration points; a plugin may never invent one.** An unrecognized key
under `integrates:` is a hard failure, exactly like an unknown `requires:` resource. The
point exists so core keeps the capability and the plugin keeps only its client's facts:

```
memory.mounts   plugin answers "where does my client keep memory directories?"
                core decides what a healthy mount is, attaches it, and rescues
                anything already there — for every client, identically
```

This is what lets one memory engine serve every client without a fork. Nothing in
`cli/ai-os-memory` names a client, and any plugin that declares `memory.mounts` gets the
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
enforces: [git]     # implements policies/git.yaml in this client's mechanism
```

A plugin *implements* a policy. It never restates one, never relaxes one, and never
defines its own. The policy lives in `policies/`, client-agnostic; the plugin is one
enforcement of it.

## Compatibility

Three versions move independently:

```
Core       0.1.x    supports a contract RANGE
Contract   1        this schema
Workspace  1        the ~/.ai-os layout
```

A plugin declaring `contract: 2` on a core supporting `1..1` is **disabled with an explicit
reason**. It is never partially applied — a half-written `CLAUDE.md` is worse than none —
and never silently upgraded, downgraded, or disabled. Breaking changes to this schema
increment `contract`, and nothing else does.
