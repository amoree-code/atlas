<!-- atlas:generated:begin -->
# Atlas Environment

Atlas is the canonical environment; engine owns reusable behavior and ~/atlas owns private data.

## Features

- setup
- onboarding
- integrations
- agentic runs
- migration
- rollback
- release gates

## Commands

- `atlas init`
- `atlas setup`
- `atlas structure plan|apply|check`
- `atlas onboard`
- `atlas integration inventory|detect|register|list`
- `atlas activity`
- `atlas agentic`
- `atlas migrate`
- `atlas update`
- `atlas docs`

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
