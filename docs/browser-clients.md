# Universal browser client setup

Atlas owns the browser workflow and task format. AI clients connect to the same
browser through a standard MCP server; client-specific setup only changes where
the MCP entry is stored.

## Recommended stack

```text
AI client -> Playwright MCP -> Chrome/Chromium -> persistent browser profile
```

Use `@playwright/mcp` for the shared browser connection. It supports headed
browser control, structured accessibility snapshots, screenshots, and an
extension mode that attaches to existing Chrome tabs and authenticated sessions.

## MCP entry

Add this entry to the client configuration (do not commit credentials or private
profile paths):

Atlas can print the same entry without writing any client configuration:

```sh
atlas mcp playwright-config
```

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--extension"]
    }
  }
}
```

For an isolated browser instead of existing tabs, omit `--extension`. For a
stable local profile, use the Playwright MCP `--config` file and set a private
`browser.userDataDir` outside this repository.

## Client-neutral task shape

The shared skill should normalize a request to:

```text
url: <starting URL>
task: <human-readable outcome>
continue: true
verify: <observable success signal>
```

The client plans; Playwright performs the browser actions; the skill requires a
post-condition after each state-changing action and stops when the success signal
is verified. Use Atlas's `atlas browser run` JSON tasks for deterministic,
repeatable workflows and persistent Atlas sessions.

## Client wiring

The same MCP entry works with Claude Code, Codex, Cursor, VS Code, Gemini CLI,
and other MCP-compatible clients. Only the configuration location differs. A
client skill is optional: MCP provides the tools, while a skill supplies the
prompt and task conventions.

## Safety boundary

Keep profiles scoped to the intended sites. Require human confirmation for
submission, upload, download, purchases, messages, or other consequential
actions. Never configure this workflow to impersonate a user in an assessment
or to bypass a site's rules.
