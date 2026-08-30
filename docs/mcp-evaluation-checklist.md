# Before adding an MCP server

Every MCP server's tool definitions load on every request, forever, whether or not the
current task uses it. That cost has to be justified per server, not assumed away. Answer
all six before installing one:

1. **Value** — what can it do that nothing already available does?
2. **Overlap** — does it duplicate a native tool, an already-connected integration, or a
   CLI you already have authenticated (e.g. `gh` for GitHub)?
3. **Permissions** — what does it get access to, and is that the minimum needed?
4. **Secrets** — does it need a credential? If so, it belongs in the environment or the
   OS keychain — never in a config file that could be committed.
5. **Reliability** — who maintains it, and what breaks when it's down?
6. **Cost** — its tool definitions load on every request, forever, not just when used.

If a server doesn't clearly win on (1) and (2), it's very likely not worth its ongoing
cost on (6). This is a genuine bar, not a formality — most candidates should fail it.
