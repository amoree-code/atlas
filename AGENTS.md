# Working in Atlas

Atlas is a local-first Node.js runtime for headless AI agents.

## Repository rules

- Keep the public repository provider-neutral and free of credentials or personal data.
- Public runtime code belongs under `src/`.
- Private user data (workspace `personal/`, `projects/`) and private technical state (workspace `profiles/`, `sessions/`, `config/`, `control-plane/`, `integrations/`, `archive/`) live at the workspace root, outside the engine, and must remain ignored by Git.
- The engine must not contain private runtime data.
- Use `sessions/sessions.sqlite` only for session metadata, session events, and parent-child links.
- Keep provider execution inside `src/infrastructure/providers/`.
- Do not add `Adapters`, `Handoff`, `Mission`, `Coordinator`, or the legacy Python/Bash runtime.
- Do not add hosted services, PostgreSQL, Redis, or dashboards to the local runtime.

## Development

```bash
pnpm install
pnpm build
pnpm test
```

Never store credentials in source, configuration, logs, tests, or documentation.
