# Context

Before a provider is invoked, `buildContext` (`src/infrastructure/filesystem/context-manager.ts`)
assembles a bounded prompt prefix from files the profile is explicitly allowed to read.

## How it works

For each path in `profile.contextSources`, in order:

1. Stop if the running byte total already reached `maxBytes` (default `32_000`).
2. Resolve the source path relative to the run's working directory (`root`).
3. Skip it unless it resolves inside one of `profile.allowedPaths` (resolved the same way) —
   either an exact match or a path underneath it.
4. Read the file as UTF-8, truncated to the bytes remaining in the budget.
5. Append it as a `## <relativePath>` section, and track it in the file list and byte count.

The result is a `BuiltContext`:

```ts
{
  content: string,          // concatenated "## path\n<contents>" sections, joined by blank lines
  manifest: ContextManifest,
}
```

## Context manifest (`src/domain/context/context.ts`)

```ts
{
  files: string[],                  // context sources actually included
  bytes: number,                    // total bytes included
  compactedSummary: string | null,  // not populated by buildContext today
  lastContextCheckpoint: string,    // ISO timestamp of this build
}
```

Validated by `validateContextManifest` (Zod). `agent-run.ts` records the manifest as a
`context_manifest` session event before the provider runs, and prefixes the prompt with
`context.content` when non-empty (see [sessions.md](sessions.md#events)).

## Access boundary

`allowedPaths` is the only enforcement point today: a `contextSources` entry outside every
`allowedPaths` entry is silently skipped, not read. This is the same `allowedPaths` list
declared on the profile (see [profiles.md](profiles.md)); there is currently no separate
context-specific allow list.
