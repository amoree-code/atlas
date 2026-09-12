# Platform validation

This matrix records observed Atlas interception boundaries. `NOT PROVEN` means the command or
host was not available for live validation; it is not a compatibility claim. Windows/Linux live
validation is intentionally deferred until supported hosts are available.

| Boundary | macOS | Linux | Windows |
|---|---|---|---|
| Managed shell shim | `PROVEN` | `NOT PROVEN` | `NOT PROVEN` |
| Interactive PTY forwarding | `PROVEN` | `NOT PROVEN` | `NOT PROVEN` |
| Absolute-path bypass detection | `PROVEN` | `NOT PROVEN` | `NOT PROVEN` |
| OpenShell filesystem/Landlock policy | `PROVEN` on the local VM path | `NOT PROVEN` on a native host | `NOT PROVEN` |
| OpenShell provider attachment | `NOT PROVEN`; no configured provider | `NOT PROVEN` | `NOT PROVEN` |
| Native desktop-client interception | `OUT OF SCOPE` | `OUT OF SCOPE` | `OUT OF SCOPE` |
| OpenShell OS-level sandbox boundary | `PROVEN` on the local VM path | `NOT PROVEN` on a native host | `NOT PROVEN` |
| Host-wide process interception | `OUT OF SCOPE` | `OUT OF SCOPE` | `OUT OF SCOPE` |

## Reproduction commands

Run from the engine package:

```sh
pnpm test
pnpm check:package
pnpm check:privacy
pnpm check:tickets
git diff --check
```

For a configured OpenShell provider, set only its provider name and let OpenShell own the
credential:

```sh
ATLAS_SANDBOX_RUNTIME=openshell ATLAS_OPENSHELL_PROVIDER=<provider-name> atlas intercept --client <client> -- <args>
```

Do not replace this with an API key in `ATLAS_OPENSHELL_PROVIDER`; it is a provider name, not a
credential. Native desktop clients are outside the current Atlas CLI scope. Absolute-path launches
and shells without the managed shim remain bypass cases until a platform-specific enforcement
adapter is separately approved.
