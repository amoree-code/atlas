# Changelog

## Unreleased

- Upgrade to pnpm 12, TypeScript 7, and Zod 4.
- Add Biome and Knip quality gates plus a unified `pnpm check` command.
- Align ticket creation and validation with the current task contract while retaining legacy-ticket compatibility.
- Exclude Git-ignored, machine-generated files from the public privacy scan.

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
