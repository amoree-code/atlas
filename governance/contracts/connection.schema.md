# Connection manifest — version 1

A connection manifest maps a known client id to its detection recipe. MCP itself is
client-agnostic; config registration is not. Unknown clients use the generic JSON path:

```bash
atlas connect --client <id> --json-config <path> --approve
```

Manifest shape:

```yaml
connection: codex
name: OpenAI Codex CLI
contract: 1
aliases: [openai-codex]
client:
  detect: [~/.local/bin/codex, ~/.codex/]
transport:
  preferred: mcp
  gateway: atlas-mcp-gateway
```

Rules:

1. MCP is the common transport; no client-specific adapter is required for the generic
   JSON path.
2. Native client registration is preferred when the client exposes it.
3. A known config recipe is the fallback when native registration is unavailable.
4. Unknown config formats are never guessed; the command requires an explicit JSON path and
   object key.
5. Client installation and Atlas connection remain separate.
6. `tools/list` is probed before reporting the gateway healthy.
