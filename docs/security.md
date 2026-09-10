# Security

## Credentials

Atlas never stores, reads, or manages provider credentials. Authentication is delegated
entirely to each provider's own CLI (`claude`, `codex`, `gemini`, `agy`) — Atlas only spawns
that binary and streams its stdout/stderr (see [providers.md](providers.md)). No API keys,
tokens, or secrets are ever written to profiles, sessions, logs, or the repository.

## Public engine / private workspace boundary

This repository contains no user data. All user and technical state lives in a private
workspace outside of `engine/` (see [workspace.md](workspace.md)), which:

- Is not part of this repository's git history.
- Is git-ignored by this repository's `.gitignore` as a safety net (`personal/*`,
  `projects/*`, `profiles/*`, and `sessions/*`) even if a workspace is ever accidentally nested inside a clone.
- Is created by `atlas setup` with `config` restricted to `0700` permissions.

## Filesystem access

Profiles declare `allowedPaths`, and `buildContext` only reads a `contextSources` entry if
it resolves inside one of those paths (see [context.md](context.md)). The schema also
carries `allowedCommands` and `writePolicy` per profile (see [profiles.md](profiles.md)),
but the current runtime does not yet enforce them — the provider CLI itself governs what it
actually reads, writes, or executes once invoked.

## Data validation

Before publication, run `pnpm check:privacy`. This read-only release-gate scan checks
non-generated source, documentation, and templates for credential patterns, real private
paths, and personal data. It reports finding types and file paths without secret values and
fails closed; license text and generated dependencies/build output are intentionally ignored.

Profiles, sessions, and context manifests are all validated against Zod schemas on read and
write (`profile-validator.ts`, `session-validator.ts`, `context-validator.ts`), so malformed
state fails fast rather than propagating silently.

## Session status integrity

Session status transitions are enforced by `assertValidStatusTransition`
(`src/domain/sessions/session.ts`): a session can only move along the documented
lifecycle (see [sessions.md](sessions.md#status-lifecycle)); `cancelled` is terminal.
