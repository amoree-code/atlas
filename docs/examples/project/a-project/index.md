---
project: a-project
role: authoritative — the work board for this project
updated: 2026-08-01
---

# Work — a-project

This board and the ticket records under `tickets/` are authoritative. Cold start reads
this file, then a ticket's own `task.md`. Resolve a bare id with
`ai-os-paths ticket <ID>`.

```
a-project/
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
| EXMPL-001 | `active` | small | — | Add CSV export to the reports page | Wire the export button to the existing `/reports/export` endpoint | [`task.md`](tickets/EXMPL-001/task.md) |

<!-- ai-os:tickets:end -->
