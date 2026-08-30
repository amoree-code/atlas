# Policies

A policy is declared once, here, client-agnostically. An adapter enforces it in whatever
mechanism its client actually supports (a hook, a config flag, a wrapper script). The
policy file never assumes a specific enforcement mechanism; the adapter never redefines
the policy, only implements it.

```
policies/git.yaml                 the rule: git.push requires approval, always
        │
        ↓ implemented by
adapters/claude-code/ai-guard-push   a PreToolUse hook that inspects Bash commands
adapters/codex/…                      not implemented yet
adapters/gemini/…                     not implemented yet
```

## V0.1 scope

Only `git.yaml` exists. This is deliberate — V0.1's job is the abstraction and the one
policy the existing system already depends on (git push protection), not a general policy
engine. A broader engine (file deletion, package installs, external messages, etc.) is
V0.7 in the roadmap, not now. Don't add speculative policy files ahead of an adapter that
actually needs them.

## Adding a policy

1. State the rule in a new `<name>.yaml` here — no adapter-specific detail.
2. Implement it in at least one adapter.
3. Record which adapters implement it in the policy file's own `enforcement:` block, so
   the gap is visible rather than assumed.
