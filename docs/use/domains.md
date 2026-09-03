# Domains

A **domain** answers *"what area of work is this, and which capabilities would delivering
it need?"* — never *"what can AI OS do?"* (that's a capability, `docs/use/capabilities.md`)
and never *"how does a client reach AI OS?"* (that's an adapter, `docs/use/adapters.md`).

**You can declare an area of work. Nothing will run it. Declaring is the feature.** Design
rationale and the full contract: `docs/design/domain-delivery.md` and
`schemas/domain.schema.md`.

## What ships today

Two domains, in `domains/`: `software` and `customer-support`.

## What a domain is

A flat file, `domains/<id>.yaml`, with exactly five fields:

```yaml
domain: software        # stable id — MUST equal the filename stem
name: Software           # human label
contract: 1
requires: [browser]      # capability ids this domain needs (optional)
outcomes:                # outcome KINDS — a set, never a sequence
  mobile-app:
    summary: a mobile application built, packaged and released
```

`requires:` names capabilities the same way a capability names its own dependencies —
no resolver, no version range, no install order. `outcomes:` is vocabulary: a name and a
summary, nothing more.

## What a domain is not

A domain has **no command, no verifier, no provider, no authority rung, and no ordering.**
There is no verb that could run one: `ai-os domain` has exactly `list` and `doctor`, both
read-only. An outcome *kind* (`mobile-app`, the vocabulary) is not the same thing as an
outcome *instance* (a specific app, for a specific client, this quarter) — the instance is
named by a task in your workspace, and it never appears in a declaration.

## Commands

```bash
ai-os domain list
ai-os domain doctor
```
