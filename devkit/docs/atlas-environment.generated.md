<!-- atlas:generated:begin -->
# Atlas Environment

Atlas is the local-first control layer; the public engine owns reusable behavior and $ATLAS_HOME owns private data.

## Features

- setup
- onboarding
- integrations
- agentic runs
- migration
- rollback
- release gates

## Commands

- `atlas setup`
- `atlas setup preflight|apply --approve`
- `atlas status|doctor`
- `atlas providers status|add|remove`
- `atlas structure plan|apply|check`
- `atlas onboard`
- `atlas adapter list|doctor`
- `atlas integration inventory|detect|register|list`
- `atlas capability list|doctor|invoke`
- `atlas activity`
- `atlas agentic`
- `atlas migrate`
- `atlas update`
- `atlas docs check|build|sync`

## Clients

- claude-code
- codex
- gemini
- cursor
- opencode

## Surfaces

- cli
- ide
- terminal
- desktop
- extension
- file
- clipboard
- api

## Channels

- cli
- ide
- terminal
- extension
- desktop
- obsidian

## Ownership

- Public reusable code: `engine/`.
- Private data and generated runtime state: `$ATLAS_HOME`.
- Client homes remain client-owned; Atlas stores bridge metadata only.

<!-- atlas:generated:end -->
