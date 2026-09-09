# a-project — why it is built this way

The standing decisions and constraints that explain the current shape of the project —
not a log of what happened (that's a ticket's `## Log`), the reasoning that is still true
today.

Example content for this fictional project:

- The reports page renders server-side; export reuses the existing `/reports/export`
  endpoint rather than adding a second code path, because the two must never disagree on
  what "the current report" means.
- CSV was chosen over XLSX for the first export format because every downstream
  consumer already parses CSV and none of them need styled cells.
