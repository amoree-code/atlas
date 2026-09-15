# Browser capability

Atlas exposes a provider-neutral browser capability through the `atlas browser` CLI.
The implementation uses `playwright-core` with an already-installed Chromium-family
browser. Atlas never downloads a browser binary during install or build.

## Lifecycle

```text
atlas browser detect
atlas browser open --profile default
atlas browser show <session-id>
atlas browser events <session-id>
atlas browser close <session-id>
```

`open` launches a headless browser on loopback CDP, persists the browser metadata in
the private `system/sessions/sessions.sqlite`, and returns an Atlas session id. Every
later operation reconnects to that session. Browser profiles and downloads stay under
the private workspace `system/browser/` directory.

## Operations

```text
atlas browser navigate <session-id> <url> [--approve]
atlas browser read <session-id>
atlas browser observe <session-id>
atlas browser extract <session-id> <selector> [--attribute <name>]
atlas browser click <session-id> <selector> --expect navigates|stays|count:<selector>:<number>
atlas browser type <session-id> <selector> <text> [--no-clear]
atlas browser select <session-id> <selector> <value>
atlas browser scroll <session-id> [delta-y]
atlas browser wait <session-id> [--selector <selector>] [--url-contains <text>]
atlas browser upload <session-id> <selector> <path>... --approve
atlas browser download <session-id> <selector> [--destination <directory>] --approve
atlas browser submit <session-id> <selector> --approve
```

Cross-origin navigation and upload/download/submit require explicit `--approve`.
Every operation returns JSON and records only bounded operation metadata in the
session event log; page content, cookies, tokens, and credentials are not persisted.

## Browser availability

Use `ATLAS_BROWSER_EXECUTABLE` to select a Chromium-family executable when the
automatic paths are insufficient. The default unit suite uses the fake provider:

```text
pnpm test
```

Run the real Playwright integration check explicitly when a local browser is
available:

```text
ATLAS_BROWSER_INTEGRATION=1 pnpm test
```

The integration test is opt-in and does not run in CI by default.

## Safety and rollback

The browser provider is isolated under `src/infrastructure/providers/`; domain and
application code use only JSON-safe browser types. Downloads sanitize remote filenames
and stay inside their destination directory. Removing the browser CLI, provider files,
tests, and `playwright-core` dependency is the rollback boundary; private runtime data
can be left untouched or removed separately by an explicit owner decision.
