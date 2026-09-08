# Examples

Worked examples of using Atlas — a seeded workspace, a project layout, a domain
declaration, a capability manifest — each small enough to read in one sitting and copy
from directly.

Nothing is seeded from here automatically: an example is something you read and adapt,
not something `atlas init` applies. The closest thing that *is* applied automatically is
`templates/workspace/`, which seeds a new `$ATLAS_HOME` — see `docs/use/install.md`.

- [`workspace/`](workspace/) — a filled-in slice of a seeded workspace: memory index,
  project registry, granted authority, completed onboarding
- [`project/`](project/) — a fictional project (`a-project`) with one ticket, showing the
  `schemas/task.md` contract end to end
- [`domain/`](domain/) — one complete `domain.yaml` for a fictional domain
  (`garden-planning`), conforming to `schemas/domain.schema.md`
- [`capability/`](capability/) — one complete `capability.yaml` for a fictional
  capability (`weather-lookup`), conforming to `schemas/capability.schema.md`

Every name in every example (`a-project`, `garden-planning`, `weather-lookup`, `Alex
Example`, `example-org`) is an obvious placeholder — adapt it, never copy it verbatim.

Reference material these examples are built from, if the worked version raises a
question it doesn't itself answer:

- `templates/workspace/` — the actual seed structure a fresh workspace gets
- `domains/software.yaml`, `domains/customer-support.yaml` — real domain declarations
- `capabilities/browser/` — the one real capability manifest that ships today
- `adapters/claude-code/` — the most complete adapter manifest

See `docs/use/getting-started.md` for the guided path through all of the above.
