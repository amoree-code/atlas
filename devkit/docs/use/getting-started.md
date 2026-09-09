# Getting started

This is the shortest supported path from a fresh clone to a checked Atlas workspace.

## 1. Clone the public engine

The repository is the reusable engine. Your private workspace is created separately.

```bash
git clone <repository-url> atlas
cd atlas
export PATH="$PWD/cli:$PATH"
```

Atlas needs only `bash`, `git`, and `python3`; there is no package manager or build step.

## 2. Run first-time setup

```bash
atlas setup
```

The wizard prepares the private workspace, checks the structure, detects client adapters,
and offers onboarding. For the approval-gated one-command flow:

```bash
atlas setup apply --approve
```

Use `atlas setup preflight` to inspect the plan without changing anything. The lower-level
commands remain available when you need one part only: `atlas init`, `atlas structure`,
`atlas onboard`, and `atlas adapter`.

## 3. Verify the installation

```bash
atlas status
atlas doctor
atlas setup preflight
```

`status` is the quick dashboard. `doctor` is the deeper read-only audit. A warning about
an optional client or tool not installed is expected; install it only when you need it.

## 4. Choose clients and providers

```bash
atlas adapter list
atlas adapter doctor
atlas providers status
atlas integration inventory
```

Adapters connect AI clients to Atlas. Providers are the selected implementations behind
capabilities. Atlas keeps both registries explicit; it does not silently install tools.

## 5. Understand the two layers

| Layer | Location | Purpose |
|---|---|---|
| Public engine | this clone | CLI, policies, adapters, capabilities, tests |
| Private workspace | `$ATLAS_HOME` (default `~/atlas`) | memory, knowledge, projects, config, runtime |

The boundary is checked by `atlas doctor` and `atlas privacy-scan`. Read
[Public and private](../design/public-private.md) before publishing changes.

## Next

Read [Installation](install.md) for custom workspace paths, [Workspace](workspace.md) for
the directory layout, and [Adapters](adapters.md) or [Capabilities](capabilities.md) for
client integration and available operations. The complete index is [Docs](../README.md).
