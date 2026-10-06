---
"ocean": minor
---

Rename the MCP tools and prompts from `atlas_*` to `ocean_*` (for example `ocean_status`, `ocean_review_task`). `tools/list` and `prompts/list` advertise only the new names; the old `atlas_*` names are still accepted by `tools/call` and `prompts/get` for one release, and a `atlas_session_promote` approval stays valid when fingerprinted under the name the caller sent. The `atlas` MCP config key (`mcpServers.atlas`) is unchanged: it identifies an already-installed client entry.
