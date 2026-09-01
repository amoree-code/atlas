# Capabilities — what AI-OS can do

**Empty by design.** No capability ships today, and none is fabricated to fill the space.

A **capability** answers *"what can AI-OS do?"* — software delivery, browser control,
automation, agent orchestration. Its contract is `../schemas/plugin.schema.md`.

An **adapter** answers *"how does an AI client reach AI-OS?"* — Claude Code, Codex,
Cursor, Gemini, OpenCode. Those live in `../adapters/`, contract
`../schemas/adapter.schema.md`.

```
client  ->  adapter  ->  AI-OS Core  ->  capability  ->  execution  ->  verification
```

Until 2026-08-31 this directory held the client manifests, which are adapters — the
inversion recorded in `AIOS-001/checkpoint.md` §13.1 and resolved by task AIOS-005.
