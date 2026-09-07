# Example: a domain

One complete, valid `domain.yaml` ([`schemas/domain.schema.md`](../../../schemas/domain.schema.md))
for a fictional domain, `garden-planning` — chosen to be obviously invented rather than
close to either domain already declared in `domains/` (`software`, `customer-support`).

`requires: [weather-lookup]` points at the fictional capability worked out in
[`../capability/`](../capability/), so the two examples read as one small, coherent (if
silly) worked scenario rather than two unrelated snippets.

Exactly five keys are legal on a domain: `domain`, `name`, `contract`, `requires`,
`outcomes` — any other key is an error, by design (see the schema's "Exactly five
fields" section for the full refusal table and why each rejected key is rejected).

A domain is **inert**: no command, no verifier, no provider, no authority rung, and no
ordering. This file declares vocabulary — outcome *kinds* — and nothing that runs.
`garden-planning.yaml` ships nowhere except here; it is not registered in `domains/` and
`ai-os domain list` will never see it.
