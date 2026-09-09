# Capabilities

A capability is one client-agnostic thing Atlas can do. It is not an adapter: adapters
connect clients, while capabilities provide operations.

## Current registry

Capability manifests live under `extensions/capabilities/`:

| Capability | Purpose | Availability |
|---|---|---|
| `browser` | controlled browser operations | core capability |
| `rtk` | optional output reduction wrapper | available when `rtk` exists |
| `serena` | optional symbol search wrapper | uses safe grep fallback when absent |
| `headroom` | optional context compression wrapper | available when `headroom` exists |

Check the machine rather than relying on this table:

```bash
atlas capability list
atlas capability doctor
```

Missing optional tools are safe: Atlas reports them unavailable and does not install them.

## Authority and verification

Every operation declares an authority ceiling:

```text
observe -> propose -> execute -> execute-with-approval -> autonomous
```

An operation is not considered verified merely because it executed. The registry keeps
availability, permission, invocation, execution, and verification as separate states.

## Invoke one operation

```bash
atlas capability invoke browser.read --dry-run
```

`invoke` handles one declared operation and stops. It does not create an autonomous plan or
agent loop. `--dry-run` checks the gate without executing the operation.

The old `plugin` command is only a compatibility alias. New manifests, paths, and docs
should use `capability`.
