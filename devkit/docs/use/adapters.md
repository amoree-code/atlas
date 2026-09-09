# Adapters

An adapter is the client-specific bridge: it tells Atlas how to detect and integrate one
AI coding client. A capability is different: it describes what Atlas can do.

## Current registry

Adapter manifests live in the public engine under
`agentic/integrations/adapters/<client>/`:

| Client | Manifest |
|---|---|
| Claude Code | `agentic/integrations/adapters/claude-code/adapter.yaml` |
| Codex | `agentic/integrations/adapters/codex/adapter.yaml` |
| Cursor | `agentic/integrations/adapters/cursor/adapter.yaml` |
| Gemini | `agentic/integrations/adapters/gemini/adapter.yaml` |
| OpenCode | `agentic/integrations/adapters/opencode/adapter.yaml` |

The authoritative list on your machine is:

```bash
atlas adapter list
atlas adapter doctor
```

## What an adapter owns

An adapter may detect its client, render Atlas configuration into that client's own config
directory, and report health. It must not own private workspace data or duplicate Atlas
policies. Core decides workspace paths and safety rules.

Client configuration stays inside the client's domain, such as `~/.claude/`, `~/.codex/`,
`~/.cursor/`, `~/.gemini/`, or `~/.config/opencode/`. A manifest that writes inside
`$ATLAS_HOME` is invalid.

## Connect a client

Known MCP clients use:

```bash
atlas connect <id> --approve
```

An unknown client requires an explicit JSON configuration path:

```bash
atlas connect --client <name> --json-config <path> --approve
```

Use [Connect](connect.md) for protocol details. Atlas never guesses an unknown client's
configuration path.

## Safety boundary

`atlas adapter doctor` validates manifests and changes nothing. `atlas adapter init` can
produce an approval-gated local draft for a detected client; it must not be used to edit
the public adapter registry directly.
