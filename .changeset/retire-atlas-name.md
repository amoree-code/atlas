---
"ocean": minor
---

**Breaking:** the legacy `atlas` name is retired (T-254). Removed: the `atlas` bin alias and shim, the `ATLAS_*` environment-variable fallbacks, `atlas_*` MCP tool/prompt names and `atlas://` URIs, the `atlas` CLI value for `obsidian conflicts resolve --keep`, `atlas-session-bootstrap` hook and `~/atlas` folder detection, legacy `atlas` startup-entry detection in `ocean setup`, the `atlas` workspace project id, task folder and `Atlas` archive namespace, and the `atlas` interception-block marker. The generated MCP config entry is now keyed `ocean` (`mcpServers.ocean`); remove any `atlas` entry left in a client config. Still read, never written: stored session/profile/context values from before the rename, Obsidian conflict records with `atlasSha256`/`atlasContent`, and a vault mirror folder named `01-Projects/Atlas`.
