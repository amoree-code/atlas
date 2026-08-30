# AGENTS.md — working in this repository

This file is for an AI agent working *on* AI OS itself (this repo), not for an AI OS
user's own project.

## What this repo is

The public, reusable half of AI OS: engine concepts, schemas, policies, adapters, skill
templates, and a CLI foundation. It contains no personal data and must never be made to
contain any — no real names, no real project names, no real file paths from a
contributor's machine, no credentials.

## Rules for this repo specifically

- Every skill and script under `templates/` must be **path-agnostic**: no assumption
  that the user's workspace lives at any specific location. Reference `$AI_OS_HOME`
  (defaulting to `~/.ai-os`), never a hardcoded path.
- Every skill and script must be **client-agnostic** where possible. Where a piece of
  behavior is genuinely one client's mechanism (e.g. a Claude Code hook contract), it
  belongs under `adapters/<client>/`, not in `templates/`.
- Never commit example data that looks like it could be real — use obviously
  placeholder values (`example.com`, `Example Org`, `a-project`) in every template.
- A policy in `policies/` states *what* must be true; an adapter states *how* one client
  makes it true. Don't let a policy file assume a specific client's implementation.

## Testing

`adapters/claude-code/tests/` holds the regression suite for that adapter. Run it before
changing `adapters/claude-code/ai-guard-push`.
