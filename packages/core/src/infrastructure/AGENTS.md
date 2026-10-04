# Infrastructure layer

Provider mechanics and I/O. Keep all provider execution inside `providers/`; this layer
implements mechanics only — capabilities and application code decide policy, not here.
`persistence/` may write `kernel/bridge/sessions/sessions.sqlite` for session metadata, session
events, and parent-child links only — nothing else. `brain/` may write only
`brain/.index/` — a derived, disposable, gitignored search index rebuilt from markdown by
`atlas memory reindex`; it is never a source of truth and nothing outside `reindex` writes to
it.

Full repository rules: [../../../../AGENTS.md](../../../../AGENTS.md).
