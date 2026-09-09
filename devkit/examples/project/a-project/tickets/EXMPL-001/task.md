---
id: EXMPL-001
title: Add CSV export to the reports page
state: active
project: a-project
opened: 2026-07-28
updated: 2026-08-01
artifacts: []
class: small
expected_context: small
---

## Objective

A user viewing the reports page can download the report they're looking at as a CSV
file, matching what's on screen.

## Definition of done

Clicking "Export CSV" on the reports page downloads a `.csv` file whose rows match the
currently filtered/sorted table, and the file opens cleanly in a spreadsheet app.

## Next action

Wire the export button to the existing `/reports/export` endpoint (it already accepts
the same filter/sort query params the table view uses) and confirm the response is
served with a CSV content type.

## Verification

```
npm test -- reports/export
```
Last result, 2026-08-01: not yet run — the button isn't wired up yet.

## Blockers

None.

## Log

- 2026-07-28 — Ticket opened. Confirmed `/reports/export` already exists and accepts the
  same query params as the table view, so no new endpoint is needed.
- 2026-08-01 — Added the "Export CSV" button to the reports page toolbar (currently a
  no-op); wiring it to the endpoint is the next action.
