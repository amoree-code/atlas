# Adapters

An **adapter** answers *"how does this AI client reach Atlas?"* It is not a capability —
a capability answers *"what can Atlas do?"* (`docs/use/capabilities.md`). Adapters are
public software, one per client, in `adapters/<client>/`. Full contract:
`schemas/adapter.schema.md`.

## What ships today

| Adapter | Directory |
|---|---|
| Claude Code | `adapters/claude-code/` |
| Codex | `adapters/codex/` |
| Cursor | `adapters/cursor/` |
| Gemini | `adapters/gemini/` |
| OpenCode | `adapters/opencode/` |

## What an adapter does

Exactly three things, and nothing else:

```
detect()        is this client present on this machine?
apply(bundle)   render core's bundle into this client's own config domain
doctor()        report this adapter's health; change nothing
```

Installing, enabling, disabling and reporting overall status are **core** operations, not
adapter behavior — an adapter never decides whether it is active, only whether the client
it targets is present and healthy.

## The rule that keeps adapters from becoming a second workspace

An adapter may declare where it writes **only inside its own client's configuration
domain** — `~/.claude/`, `~/.codex/`, `~/.gemini/`, `~/.cursor/`,
`~/.config/opencode/` — and never under `$AI_OS_HOME`. `ai-os doctor` rejects any manifest
that tries. When an adapter needs workspace data, it asks core for it by name (a resolved
path, a rendered bundle) rather than reaching in itself.

Some clients need one fact only they can supply — for example, where Claude Code keeps its
per-project memory directories, since it scopes its own memory tool by working directory.
An adapter declares that single fact under `integrates:` in its manifest; core owns
everything downstream of it. See `docs/use/memory.md` for what this solves.

## Enforcement

A policy (`docs/design/governance.md`) states *what* must be true, client-agnostically. An
adapter states *how* its client makes that true — implementing the policy, never
restating or relaxing it.

```bash
ai-os adapter list
ai-os adapter doctor
```
