# internal/

Tooling-only. Nothing here is part of AI OS's product surface — no CLI verb, no schema, no
capability, no adapter, no doc a user needs to read to use the system.

What belongs here is background material for people working *on* this repository: build
and release tooling, and generated output that has to live somewhere but isn't source.
`graphify-out/` is the current example — derived, gitignored, rebuilt on demand, never
authoritative.

If you're looking for the software AI OS ships, start at the root
**[README.md](../README.md)** instead.
