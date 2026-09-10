# Troubleshooting

## `atlas run` prints "Usage: atlas run --profile <name> --prompt <text>"

Both `--profile` and `--prompt` are required. `--prompt` consumes every argument after it
as the prompt text (`src/main.ts`), so pass it last.

## Profile load fails

`loadProfile` reads `<workspace>/profiles/<name>.json` and validates it with Zod
(see [profiles.md](profiles.md)). Failures mean either the file does not exist (run
`atlas setup` to create `profiles/default.json`, or add the named profile yourself)
or it does not match the schema — check `provider` is one of `claude`/`codex`/`gemini`/
`antigravity` and every required field is present.

## Session resume rejected: "Provider does not support resume yet"

`resumeAgent` only supports sessions whose `provider` is `claude` and that already recorded
a `providerSessionId` from a prior run (see [sessions.md](sessions.md#cli-usage)). Check
`atlas session show <id>` — if `providerSessionId` is `null`, the original run never
reported one (the provider's stdout never emitted a `session_id` field), and that session
cannot be resumed.

## Provider process fails immediately or times out

- Confirm the provider CLI is installed and on `PATH`: `claude`, `codex`, `gemini`, or
  `agy` for `antigravity` (see [providers.md](providers.md)). Atlas does not verify this
  before spawning.
- Confirm the provider CLI is authenticated on its own terms — Atlas does not manage or
  check credentials.
- The default subprocess timeout is 60,000 ms; a run that legitimately needs longer will be
  killed with `SIGTERM` and reported as exit code `124`. Inspect
  `atlas session show <id>` and its events for the `process_exit` payload.

## Workspace ends up in the wrong place

`atlasRoot()` defaults to the parent directory of the running `engine/` checkout; set
`ATLAS_ROOT` to point at a different workspace root (see [workspace.md](workspace.md)).
Re-run `atlas setup` after changing `ATLAS_ROOT` to bootstrap the new location.

## Private workspace directories show up in `git status`

They should not — this repository's `.gitignore` excludes `personal/*`, `projects/*`, and
private workspace directories (see [security.md](security.md)). If they appear, the workspace root may have
been accidentally created inside `engine/`; check `ATLAS_ROOT` and the location `atlas
setup` reported.
