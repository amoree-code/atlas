# tests/_tmp — disposable, not contract

Temporary and generated tests for the current Fast-Track development phase (see the
private workspace's `user/04-projects/atlas/dev-mode.md` — not duplicated here).

```
_tmp/
├── <slice-id>/    one-off diagnostics for a specific slice, created on demand
├── generated/     generated test cases
├── regression/    temporary regression checks not yet promoted
└── repeated/      repeated experiments run during investigation
```

Rules:

- Never mixed with the permanent contract suite (`tests/test-contract.sh`,
  `tests/fixtures/`). Nothing here is part of Atlas's tested public contract.
- Before adding a new one-off test, search this directory for an existing test covering
  the same behavior and extend it instead — no `test_x_2` / `test_x_final` variants.
- A test that proves a durable invariant gets promoted into `tests/test-contract.sh`. One
  that only supported a single investigation stays here, disposable.
- Never modify production behavior to make a temporary test pass.

At V1.0 / release-hardening: review this directory, promote what's durable, delete the
rest, and remove Fast-Track Mode from the development protocol.
