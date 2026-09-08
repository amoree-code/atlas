# AGENTS.md — working in this repository

This file is for an AI agent working *on* Atlas itself (this repo), not for an Atlas
user's own project.

## What this repo is

The public, reusable half of Atlas: engine concepts, schemas, policies, adapters,
capabilities, domain declarations, skill templates, and a CLI. It contains no personal
data and must never be made to contain any — no real names, no real project names, no
real file paths from a contributor's machine, no credentials.

## Rules for this repo specifically

- Every skill and script under `templates/` must be **path-agnostic**: no assumption
  that the user's workspace lives at any specific location. Reference `$ATLAS_HOME`
  (defaulting to `~/atlas`), never a hardcoded path.
- Every skill and script must be **client-agnostic** where possible. Where a piece of
  behavior is genuinely one client's mechanism (e.g. a Claude Code hook contract), it
  belongs under `adapters/<client>/`, not in `templates/`.
- Never commit example data that looks like it could be real — use obviously
  placeholder values (`example.com`, `Example Org`, `a-project`) in every template.
- A policy in `internal/governance/policies/` states *what* must be true; an adapter states
  *how* one client makes it true. Don't let a policy file assume a specific client's
  implementation.

## The docs are part of the product, so a false doc is a bug

Docs here have drifted behind the tree before. Check the claim against the filesystem
before you write it down, and prefer deleting a stale sentence to carrying it forward.

- **Never list a path that does not exist.** Layout blocks, command lists and schema
  lists go stale first. Verify each entry before editing one.
- **Never say a thing does not exist without looking.** Check `capabilities/`,
  `adapters/`, `internal/governance/policies/`, `schemas/` and `domains/` first. "Empty by
  design" and "none ship yet" were both false for months.
- **There are two layers, not three.** `~/.ai` is retired: the engine is `cli/`, client
  integration is `adapters/<client>/`, and transient state is `$ATLAS_HOME/runtime/`.
  `atlas doctor` fails if the legacy location still holds active components.
- **A unit of behavior is a `capability`**, contract `schemas/capability.schema.md`.
  A client integration is an **adapter**, contract `schemas/adapter.schema.md`. Never
  use either word for the other, in a filename, an identifier or a sentence. `plugin` is
  the historical name for a capability and survives only as compatibility — the
  `atlas plugin` alias, the `ATLAS_PLUGINS` env fallback, the `plugin.yaml` manifest
  fallback, and the `plugin:` manifest key in contract v1. Never use it as the current
  term.
- **A domain declares; nothing executes it.** `domains/<id>.yaml` has no command, no
  verifier, no provider, no authority and no ordering. Don't write prose implying a
  pipeline, an engine, an orchestrator, or "running" a domain.
- **State enforcement honestly.** If a policy is written down but no code reads it, say
  so. A visible gap is the point; an assumed one is the defect.
- **Keep `VERSION` and any version claim in `README.md` in agreement.**
- **No absolute paths from a contributor's machine**, and no real memory content in an
  example. `$ATLAS_HOME` (default `~/atlas`) is the public referent.

`atlas privacy-scan` is the backstop for the last rule only. Nothing automated checks the
others, which is why they are written here.

## Testing

`adapters/claude-code/tests/` holds the regression suite for that adapter. Run it before
changing `adapters/claude-code/ai-guard-push`.
