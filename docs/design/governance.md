# Governance

**Governance** is the concept: the rules a policy declares, the authority ladder a
capability operation is checked against, and the approval boundaries that gate anything
hard to reverse. It is client-agnostic by construction — a policy states *what* must be
true; each adapter states *how* its client makes that true, and never restates or relaxes
the policy itself.

## Where it lives today

```
governance/
├── README.md      the index
└── policies/      the declarations themselves
```

Policy declarations moved from a top-level `policies/` to `governance/policies/` on
2026-09-03. There is deliberately no `governance/rules/`: no public, client-agnostic rules
content exists yet, and an empty namespace would be the placeholder problem this
repository has already refused once. A user's own behavioural rules live in their private
workspace, not here.

## What exists, and what enforces it

Read `governance/README.md` for the current, honest inventory — which policy file exists,
and which command actually reads it versus which one is enforced only because code was
written by hand to match the written-down rule. **No command in this repository parses a
policy file.** Each enforced rule is enforced by code that was written to match the
policy; the policy file is the source that implementation answers to, which is what makes
drift between them a real risk worth writing down rather than an impossible one.

This is a small set on purpose. A policy lands here because something already enforces
it, or because the boundary it describes is load-bearing enough to write down and audit —
not ahead of either. A general policy engine (file deletion, package installs, outbound
messages) is a later, deliberate version: see `docs/design/decisions.md` for why AI OS
stays this size on purpose.

## The authority ladder

Every capability operation declares the rung of authority it needs:

```
observe  ->  propose  ->  execute  ->  execute-with-approval  ->  autonomous
```

An operation may never exceed its capability's declared ceiling, and a capability may
never exceed what policy grants. `autonomous` is not implementable today — a manifest
requesting it is rejected outright, which is what keeps a future automation layer from
arriving as a flag instead of a deliberate version. Detail: `docs/use/capabilities.md`.

## Approval at the boundary

The one policy every part of this system already depends on: pushing to a remote requires
explicit approval, always — `governance/policies/git.yaml`, implemented by hand in
`adapters/claude-code/ai-guard-push`. The public/private boundary itself is also governance
in this sense: `docs/design/public-private.md` is the policy, in prose; `ai-os doctor` is
the enforcement.
