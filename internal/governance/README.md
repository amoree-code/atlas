# Governance

The rules Atlas holds itself to: what must be true, declared once and client-agnostically.
An adapter enforces a rule in whatever mechanism its client actually supports (a hook, a
config flag, a wrapper script). The policy file never assumes a specific enforcement
mechanism; the adapter never redefines the policy, only implements it.

```
internal/governance/policies/git.yaml           the rule: git.push requires approval, always
        │
        ↓ implemented by
adapters/claude-code/ai-guard-push     a PreToolUse hook that inspects Bash commands
adapters/codex/…                       not implemented yet
adapters/gemini/…                      not implemented yet
```

## Layout

```
internal/governance/
├── README.md      this file
└── policies/      the declarations themselves
```

There is deliberately no `internal/governance/rules/`. No public, client-agnostic rules content
exists yet, and an empty namespace would be the placeholder problem this repository has
already refused once. The user's own behavioural rules live in their private workspace,
not here.

## What exists today

| File | States | How it is honoured |
|---|---|---|
| `policies/git.yaml` | `git.push` requires explicit approval, always | implemented by hand in `adapters/claude-code/ai-guard-push`, which does not parse this file |
| `policies/public-private-contract.yaml` | the public/private boundary, as machine-readable policy | implemented by hand in `atlas init` and `atlas doctor`, which do not parse this file |
| `policies/privacy-classification.yaml` | what counts as a credential versus personal data | implemented by hand in `atlas privacy-scan`, which does not parse this file |
| `policies/workspace-privacy.yaml` | what requires approval at the boundary | not honoured by any code yet |
| `policies/handoff-transports.yaml` | which handoff transports are verified, and their pinned read-only modes | read at runtime by `atlas handoff` |

Read that column carefully, because it is the honest one. **No command in this repository
parses a policy file** — with `handoff-transports.yaml` as the one exception, which is a
registry rather than a declaration. Each rule that is enforced is enforced by code that was
written to match the policy, and each file is the written-down source those implementations
answer to — which is what makes drift between them a real risk rather than an impossible
one.

`policies/privacy-allowlist.txt` is the other file here that *is* loaded at runtime, and it
is scan input rather than a policy: the strings `atlas privacy-scan` is allowed to ignore.

## Still not a policy engine

This is a small set on purpose. A policy lands here because something already enforces it,
or because the boundary it describes is load-bearing enough to write down and audit — not
ahead of either. A general engine covering file deletion, package installs and outbound
messages is a later, deliberate version, and it is the thing that would finally make these
files executable rather than declarative. Don't add a speculative policy file before the
adapter or command that would honour it.

## Adding a policy

1. State the rule in a new `policies/<name>.yaml` here — no adapter-specific detail.
2. Implement it in at least one adapter.
3. Record which adapters implement it in the policy file's own `enforcement:` block, so
   the gap is visible rather than assumed.
