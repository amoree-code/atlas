# Examples

Worked examples of using AI OS — a seeded workspace, a project layout, a domain
declaration, a capability manifest — each small enough to read in one sitting and copy
from directly.

Nothing is seeded from here automatically: an example is something you read and adapt,
not something `ai-os init` applies. The closest thing that *is* applied automatically is
`templates/workspace/`, which seeds a new `$AI_OS_HOME` — see `docs/use/install.md`.

This directory is currently a placeholder for that content rather than a populated set of
examples. Until real examples land here, the most useful reading is:

- `templates/workspace/` — the actual seed structure a fresh workspace gets
- `domains/software.yaml`, `domains/customer-support.yaml` — real domain declarations
- `capabilities/browser/` — the one real capability manifest that ships today
- `adapters/claude-code/` — the most complete adapter manifest

See `docs/use/getting-started.md` for the guided path through all of the above.
