# Example: a workspace

What `templates/workspace/` looks like after `atlas init` has seeded it **and** its owner
has actually used it for a while — not the empty seed itself (that is
`templates/workspace/`, applied automatically by `atlas init`), a small slice of it
filled in by hand.

Four files, each the filled-in counterpart of the matching template:

- [`personal/memory/MEMORY.md`](personal/memory/MEMORY.md) — the index after a first
  identity/preferences pass, instead of the all-empty seed
- [`projects/registry.md`](projects/registry.md) — one real project row instead of the
  placeholder example row
- [`internal/config/authority.yaml`](internal/config/authority.yaml) — one capability
  actually granted, instead of `capabilities: {}`
- [`internal/config/workspace.yaml`](internal/config/workspace.yaml) — onboarding marked
  `initialized` instead of `uninitialized`

Everything else a fresh workspace gets — the full memory/knowledge section tree, the
policy text (`internal/governance/policies/privacy-terms.txt`), the model-routing file
(`internal/config/models.yaml`) — is unchanged from `templates/workspace/` and is not
repeated here; read that directory for the rest. Directories `atlas init` creates but
that ship no static content of their own (`internal/helpers/`, `internal/runtime/`,
`internal/schemas/`) aren't part of the static template either, so they aren't part of
this example.

Every name below (`Alex Example`, `a-project`, `example-org`) is an obvious placeholder —
adapt it, never copy it verbatim. See `docs/examples/project/` for what `a-project`
itself looks like.
