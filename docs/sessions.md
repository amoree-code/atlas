# Sessions

Every `atlas run` or `atlas session resume` creates or continues a session record: what
was run, for which profile, its provider-side session id, its status, and its event log.
Sessions are persisted in SQLite so they survive process restarts and can be listed,
inspected, or resumed later.

## Storage

`SessionStore` (`src/infrastructure/persistence/session-store.ts`) opens
`<workspace>/sessions/sessions.sqlite` (via `atlasPath("sessions", "sessions.sqlite")`,
see [workspace.md](workspace.md)) with `node:sqlite`, in WAL mode, and creates three tables
if absent:

- `sessions` — one row per session: id, provider, provider-side session id, parent session
  id, profile name, profile identity (see [profiles.md](profiles.md#session-reproducibility-profileidentity)),
  working directory, status, timestamps, and opaque `resume_data`.
- `session_events` — an append-only log per session (`type`, `data`, `created_at`),
  auto-incrementing `event_id`.
- `session_links` — parent/child session id pairs, for sessions created by `resumeAgent`
  or with an explicit `parentSessionId`.

`openSessionStore()` ensures the `sessions/` directory exists and returns a `SessionStore`;
callers must `close()` it when done.

## Session schema (`src/domain/sessions/session.ts`)

```ts
{
  sessionId: string,
  provider: string,
  providerSessionId: string | null,
  parentSessionId: string | null,
  profile: string,
  profileIdentity: string,             // default "" for sessions created before this field existed
  workingDirectory: string,
  status: "created" | "running" | "completed" | "failed" | "cancelled",
  createdAt: string,
  updatedAt: string,
  resumeData: string | null,
}
```

Rows are validated with Zod (`validateSession`) on both write and read.

## Status lifecycle

```
created → running → completed → running → ...
                   → failed    → running → ...
                   → cancelled  (terminal)
```

`assertValidStatusTransition` enforces this: `completed` and `failed` describe the outcome
of the most recent run, not whether the session can run again, so both can transition back
to `running` on resume. `cancelled` has no outgoing transitions.

## CLI usage

```bash
node dist/main.js session list
node dist/main.js session show <session-id>
node dist/main.js session resume <session-id> "<prompt>"
```

- `list` prints all sessions as JSON, newest first.
- `show <id>` prints one session or exits 1 if not found.
- `resume <id> "<prompt>"` currently only supports sessions whose `provider` is `claude`
  and that already have a `providerSessionId`; it re-invokes the provider with
  `--resume <providerSessionId>` (see [providers.md](providers.md)) and appends a
  `resume_requested` event before running.

## Events

Every provider event and lifecycle transition is appended to `session_events` via
`appendEvent`, including `context_manifest` (the built context, see [context.md](context.md)),
each provider stdout event (bounded to 64,000 characters), `process_exit`, and `error` on
failure. `listEvents(sessionId)` returns the full ordered log for a session.

Successful and unsuccessful provider exits also append a bounded `evidence` event. Evidence
records include a source, timestamp, result (`proven`, `not_proven`, or `limitation`), an
optional acceptance criterion, and bounded payload. Provider output is evidence input; it is
not a verified fact until a check records the corresponding result.

Runtime diagnostics are written as bounded JSON Lines at the private workspace path
`logs/runtime.jsonl`. Records contain correlation/session ids and lifecycle status only;
secrets, private home paths, prompts, and provider documents are redacted or excluded.
