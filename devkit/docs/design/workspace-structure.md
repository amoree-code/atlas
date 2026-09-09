# Why the workspace is shaped this way

The current layout is in [Workspace](../use/workspace.md). This is the reasoning behind it.

## Two halves, not one flat tree

A user should be able to hold the whole workspace in their head with three ideas:
`personal/` is long-lived personal material, `projects/` is work state, and `system/`
is Atlas machinery, and that now includes `sessions/`, which moved under
`system/` after the layout settles. They should not need to understand an
orchestrator, an event bus, or an adapter's internals to use the system. That is the
"simple for the user, not simple internally" principle in `docs/design/decisions.md`:
internal machinery is allowed to be intricate; the thing the user has to hold in their head
is not.

`mcp/` and private capability material sit under `internal/extensions/` because they are
Atlas extension points, not daily personal material and not project-owned work.

## Why numbered sections

The old numbered `user/` sections were retired by the private layout move. The current
daily-use roots are readable names: `personal/` and `projects/`, with everything the
system owns — session records included — under `internal/`.

## Memory's eight sections, knowledge's seven kinds

Both counts come from the same discipline: enumerate the categories that are actually
distinct, and stop. A ninth memory section or an eighth knowledge kind gets added only when
an existing one demonstrably fails to hold a real fact — not speculatively, ahead of any
fact that would go there. See `docs/design/memory-architecture.md` for what the eight and
seven actually are.

## Ownership classes, and why an update never overwrites

Every file `atlas init` creates is `system-default`, `user-owned`, `generated`, or
`runtime` — a class that decides what a future update may do to it. The rule that follows
from all four: **an existing file is never overwritten automatically.** A workspace that
silently rewrote your files on `init` re-run would not be a workspace you could trust
enough to put real memory in. See `docs/design/public-private.md` for the full ownership
model, shared with the public/private boundary itself.

## Why templates are seeds, not a sync

The alternative — reapplying an updated template over a user's edited file — requires a
three-way merge to be safe, and a three-way merge that gets it wrong on personal data is
worse than not merging at all. So `init` only ever writes where nothing exists, and
reports divergence rather than resolving it. This is the same reasoning as the ownership
classes above, applied to one specific case that comes up on every version bump.

## Why `mcp/` and `plugins/` are reserved rather than absent from the diagram

A namespace that is documented but not yet populated is a small, cheap promise: "this is
where it goes when it exists." Omitting it from the layout entirely would mean inventing a
location later, under time pressure, without the deliberation a workspace-root decision
deserves. This is the same instinct that keeps Atlas from building an autonomous task
engine before Domain Delivery earns one — see `docs/design/decisions.md` and
`docs/design/domain-delivery.md`.
