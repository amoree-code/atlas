# Infrastructure layer

Provider mechanics and I/O. Keep all provider execution inside `providers/`; this layer
implements mechanics only — capabilities and application code decide policy, not here.
`persistence/` may write `system/sessions/sessions.sqlite` for session metadata, session
events, and parent-child links only — nothing else.

Full repository rules: [../../AGENTS.md](../../AGENTS.md).
