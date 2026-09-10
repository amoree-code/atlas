# Migration

There is no data-migration tooling in the current runtime: no schema-versioned migrations,
no CLI command, and no automatic transformation of existing workspace data. This document
describes what changes between versions and what to check by hand.

## Workspace state

`config/settings.json` currently contains only `{ "version": 1 }`
(`templates/config/settings.json`). Nothing in the runtime reads or acts on this field
today; it exists as a placeholder for future compatibility checks.

## SQLite schema

`SessionStore` (`src/infrastructure/persistence/session-store.ts`) creates its tables with
`CREATE TABLE IF NOT EXISTS`. Upgrading the engine does not alter an existing
`sessions.sqlite` schema — a new column or table added in a future version would require a
manual migration step, not currently provided. Back up
`<workspace>/sessions/sessions.sqlite` before upgrading if you want a rollback point
(see [sessions.md](sessions.md)).

## Profiles

Profile files are plain JSON validated against `profileSchema`
(see [profiles.md](profiles.md)). If a future engine version adds a required field, an
existing profile written for an older version will fail validation until it is updated by
hand — there is no automatic profile upgrade.

## Moving a workspace

Since the workspace is a private directory separate from this repository
(see [workspace.md](workspace.md)), moving it is a plain filesystem operation: copy the
workspace root (or `config/`, `profiles/`, `sessions/`, and `personal/`/`projects/` individually) to the new location,
then point `ATLAS_ROOT` at it (or place `engine/` as its sibling again for the default
resolution). Re-run the platform startup installer (`atlas setup`) if the workspace path
changed, so the OS-level startup entry points at the correct working directory.
