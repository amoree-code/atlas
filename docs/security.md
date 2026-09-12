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
carries `allowedCommands` and `writePolicy` per profile (see [profiles.md](profiles.md)). Direct
interception keeps provider-owned execution behavior. Set `ATLAS_SANDBOX_RUNTIME=openshell` to
route the provider through an OpenShell sandbox with a bounded working directory, read-only
system paths, temporary write access, and Landlock best-effort enforcement. The current
sandbox-first path does not require an OpenShell provider attachment to create the sandbox;
missing provider credentials remain an explicit authentication failure. Atlas does not copy or
invent credentials. Secure provider attachment is a separate authentication boundary. The official
OpenShell local-credential bootstrap can be enabled only with the explicit
`ATLAS_OPENSHELL_AUTO_PROVIDERS=1` runtime policy; the default remains `--no-auto-providers`.
An existing OpenShell provider can be attached with `ATLAS_OPENSHELL_PROVIDER=<name>`; Atlas
passes only the provider name and never reads or persists the credential. If unset, no provider
is attached and authentication fails closed.

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

## Installation and bypass boundaries

`atlas install` uses only cataloged package-manager recipes and requires `--yes`. Unknown
clients and arbitrary URLs are rejected. `atlas update` repeats the approved recipe; `atlas
remove` removes only Atlas registration, wrappers, and receipts. Provider binaries, user data,
and provider-owned credentials remain outside Atlas ownership.

Native desktop clients, absolute-path launches, unconfigured shells, and operating-system
processes outside the managed shim remain explicit bypass boundaries. Atlas reports these when
detectable; it does not claim universal interception. Windows/Linux live proof and provider
credential attachment through OpenShell require platform/provider capabilities not available
to the current macOS runtime. See [platform-validation.md](platform-validation.md) for the
current evidence matrix and reproduction commands.
