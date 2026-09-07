---
project: <project>
role: authoritative — the work board for this project
updated: <YYYY-MM-DD>
---

# Work — <project>

This board and the ticket records under `tickets/` are authoritative. Cold start reads
this file, then a ticket's own `task.md`. Resolve a bare id with
`ai-os-paths ticket <ID>`.

```
<project>/
  index.md          this board
  context/           state · roadmap
  tickets/<ID>/      the authoritative unit of work — task.md plus its own artifacts
```

## Tickets

<!-- ai-os:tickets:begin -->
<!-- Generated from tickets/*/task.md by `ai-os tickets index --write`.
     The records are authoritative; this table is a view. Do not hand-edit. -->

| ID | State | Class | Role | Title | Next action | Record |
|---|---|---|---|---|---|---|

<!-- ai-os:tickets:end -->
