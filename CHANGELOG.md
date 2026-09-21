# Changelog

## Unreleased

- Make `package.json` the single version authority and remove the duplicate `VERSION` file.
- Replace the stale partial CLI help text with a grouped catalog of every top-level command.
- Ignore generated Graphify analysis output and document the current CLI module boundary.
- Upgrade to pnpm 12, TypeScript 7, and Zod 4.
- Add Biome and Knip quality gates plus a unified `pnpm check` command.
- Align task creation and validation with the current task contract while retaining legacy-task compatibility.
- Exclude Git-ignored, machine-generated files from the public privacy scan.
- Add an interactive approval gate for pending observations (capped to the 5 most recent);
  approving one now creates a skill candidate, with signal quality scoped to user input.
- Surface task observations in the daily narrative, and generate a human-readable session
  closeout and daily narrative with an opt-in model call.
- Wire in `graft` for local code-graph context during development.
- Harden Atlas runtime contracts and recovery, and fix newline-delimited JSON-RPC framing
  for the MCP stdio transport.
- Add reviewed skill learning from completed sessions, with auto-activation of reviewed skills.
- Add Kilo and Kimi as supported headless providers.
- Add provider-neutral MCP setup and complete Atlas client integration.
- Add governed Obsidian vault integration: read-only discovery, automatic hash sync, guarded
  writes, inbox promotion, and exposure through the provider-neutral MCP server.
- Make Atlas client-neutral with bounded context and cross-client sync (T-198); remediate
  security-audit findings.
- Add workspace context and safe maintenance commands (`atlas doctor`, `atlas repair`),
  `.nvmrc`/lefthook for local dev tooling, and a cross-platform Docker release gate.

## 0.3.6

- Add Hermes as a supported headless provider.
- Generate Hermes wrappers and invoke its native one-shot mode.

## 0.3.5

- Run headless providers through their original executable when Atlas shims are on `PATH`.
- Add coverage proving headless execution bypasses the managed shims.

## 0.3.4

- Make the `atlas` CLI available through the managed shell shim after setup.
- Verify the generated Atlas CLI wrapper forwards commands to the engine.

## 0.3.3

- Fix shell detection for Atlas CLI shim setup.
- Keep the public release gate green on the current mainline.

## 0.3.2

Release candidate for the Atlas v2 public engine foundation.

- Provider-neutral headless CLI execution for Claude, Codex, Gemini, and Antigravity.
- Validated profiles, bounded context, SQLite sessions, evidence, capabilities, MCP approval,
  run contracts, structured logs, Agent Skills, and release/privacy gates.
- Private workspace data remains outside the public engine package.

Publication remains subject to the release gate and owner approval.
