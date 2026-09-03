# Why the workspace is shaped this way

The layout itself is in `docs/use/workspace.md`. This is the reasoning behind it.

## Two halves, not one flat tree

A user should be able to hold the whole workspace in their head with two ideas: `user/` is
everything they own — memory, knowledge, daily records, projects — and `system/` is
configuration and governance. Everything else in the workspace hangs off one of those two,
or is transient (`runtime/`, `sessions/`). They should not need to understand an
orchestrator, an event bus, or an adapter's internals to use the system. That is the
"simple for the user, not simple internally" principle in `docs/design/decisions.md`:
internal machinery is allowed to be intricate; the thing the user has to hold in their head
is not.

`mcp/` and `plugins/` sit at the workspace root rather than under `user/` or `system/`
because neither is data you own or configuration you set — both are reserved namespaces
with ownership rules, waiting for something to exist in them. Putting a reserved,
currently-empty namespace inside `user/` would make it look like personal data; inside
`system/` would make it look like config. It is neither yet, so it gets its own place.

## Why numbered sections

`user/00-inbox/` through `user/06-templates/` are numbered so a directory listing sorts in
reading order — inbox before daily before personal before professional before projects
before knowledge before templates — rather than alphabetically, which would put `daily`
before `inbox` and scramble the intended flow from unprocessed input to durable record.
The numbers are a sort key, not a version or a priority ranking.

## Memory's eight sections, knowledge's seven kinds

Both counts come from the same discipline: enumerate the categories that are actually
distinct, and stop. A ninth memory section or an eighth knowledge kind gets added only when
an existing one demonstrably fails to hold a real fact — not speculatively, ahead of any
fact that would go there. See `docs/design/memory-architecture.md` for what the eight and
seven actually are.

## Ownership classes, and why an update never overwrites

Every file `ai-os init` creates is `system-default`, `user-owned`, `generated`, or
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
deserves. This is the same instinct that keeps AI OS from building an autonomous task
engine before Domain Delivery earns one — see `docs/design/decisions.md` and
`docs/design/domain-delivery.md`.
