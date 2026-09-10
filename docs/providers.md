# Providers

Atlas runs agents by shelling out to the provider's own CLI as a headless subprocess. It
does not call any provider API directly and does not store or manage provider credentials —
authentication is entirely the installed CLI's responsibility.

## Supported providers

`HeadlessProvider` (`src/infrastructure/providers/providers.ts`) is one of:

- `claude`
- `codex`
- `gemini`
- `antigravity`

## Requirement

The provider's CLI binary must be on `PATH`:

- `claude`, `codex`, `gemini` are invoked by their own command name.
- `antigravity` is invoked as `agy`.

If the binary is missing, the spawn fails at run time (surfaced as an `error` session
event); Atlas performs no live verification that a provider is installed or authenticated
before invoking it.

## Invocation shape (`buildProviderInvocation`)

| Provider | Command | Args |
|---|---|---|
| `claude` | `claude` | `[--resume <id>]? -p <prompt> --verbose --output-format stream-json` |
| `codex` | `codex` | `exec --json <prompt>` |
| `gemini` | `gemini` | `--prompt <prompt> --output-format stream-json` |
| `antigravity` | `agy` | `--print <prompt> --output-format stream-json` |

Only `claude` currently supports `--resume`; `resumeAgent` in
[sessions.md](sessions.md#cli-usage) rejects resume for any other provider.

## Execution (`runProvider` → `runHeadless`)

`runProvider` builds the invocation and calls `runHeadless`
(`src/infrastructure/process/cli-process.ts`), which:

- Spawns the command with `cwd` set to the agent's working directory and `stdio` set to
  ignore stdin, pipe stdout/stderr.
- Splits stdout into lines; each line is parsed as JSON if possible (emitted as a `"json"`
  event) or kept as raw text (emitted as a `"text"` event) and forwarded to `onEvent`.
- Applies a timeout (default 60,000 ms); on timeout the process is sent `SIGTERM` and the
  result reports exit code `124`.
- Resolves with `{ exitCode, events, stderr }` once the process closes.

Provider-side session ids are captured opportunistically: if a `"json"` event's data
contains a `session_id` field, `agent-run.ts` stores it as the session's `providerSessionId`
for later resume.

`discoverProviderCapabilities()` checks whether the selected CLI is installed and returns its
headless, resume, streaming, structured-output, and CLI-managed authentication contract.
`assertProviderCapability()` fails clearly before an unsupported operation. One session uses
one selected provider; Atlas does not silently fall back to another provider.
