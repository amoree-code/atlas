# Example: a capability

One complete, valid `capability.yaml`
([`schemas/capability.schema.md`](../../../schemas/capability.schema.md)) plus a
provider-interface reference, for a fictional capability, `weather-lookup` — invented to
pair with the fictional `garden-planning` domain in [`../domain/`](../domain/)
(`requires: [weather-lookup]`), purely as illustration. It is not registered in
`capabilities/` and `atlas capability list` will never see it.

```
weather-lookup/
  capability.yaml           the manifest — one operation, authority: observe
  providers/interface.py    the provider boundary this capability's command: would call
                            through — modelled on capabilities/browser/providers/interface.py
```

`command: weather-lookup` in the manifest names a bare filename that would need to exist
beside it (a real, executable script) for the capability to actually be invocable — see
`capabilities/browser/browser` for what that looks like for a real, shipped capability.
No such script is shipped here, because this capability does nothing real; only the
manifest and the provider boundary it would call through are worked out.
