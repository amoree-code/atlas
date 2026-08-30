# Workspace versioning

The user's workspace (`$AI_OS_HOME`, default `~/.ai-os`) is a **local git repository with
no remote**. This document is about why that distinction is load-bearing.

## Versioning is not publishing

```
Local git                          Remote git
─────────                          ──────────
history                            distribution
rollback                           collaboration
audit                              backup-by-someone-else
change tracking                    permanence outside your control
```

The workspace gets the left column. It does not get the right one. These are separate
capabilities that happen to share a tool, and conflating them is how personal data ends
up somewhere it can't be recalled from.

## Why this matters more than it looks

A workspace holds identity, memory, career and education records, private project and
client names, and session history. Two properties of git make that combination sharp:

1. **History is permanent.** Deleting a file in a later commit does not remove it from
   history. Anything committed once is committed for the life of the repository.
2. **Commits carry identity.** Every commit records the configured `user.email`, whether
   or not that address appears anywhere in the tree.

Neither matters while the repo is local. Both matter the instant a remote exists — and by
then it is too late to undo cheaply. That asymmetry is the whole argument for making
"local-only" the enforced default rather than a convention.

## The guards, and what each is actually worth

| Guard | Catches | Honest limit |
|---|---|---|
| **No remote configured** | everything — there is nowhere to push | someone can add one |
| `pre-push` hook | a push after a remote was added | `--no-verify` bypasses it |
| `pre-commit` hook | credential-shaped strings entering history | pattern-based; not PII-aware by design |
| Agent-level command guard | an agent running push/remote commands | adapter-specific |
| `ai-os workspace status` | remotes, nested repos, missing hooks | reports; does not block |

Only the first is a guarantee. The rest are defense-in-depth: they turn a silent accident
into a loud one. Treat the hooks as smoke alarms, not locks.

Note the `pre-commit` hook scans for **credentials, not personal information**. Personal
data is the intended content of the workspace — blocking it would make the workspace
useless. Credentials are different: they have no reason to be there at all.

## Nested repositories are a defect, not a setting

The public AI OS repository and the private workspace must never contain one another.
When tooling finds a nested repository it **reports it loudly**; it never adds it to
`.gitignore`. Ignoring a nested repo makes the problem invisible while leaving it in
place, which is strictly worse than the problem.

## Snapshot model

One commit per **completed task**, not per file write.

```
Task → Execute → Update workspace state → Verify → snapshot → one local commit
```

A finished task typically touches several areas at once — memory, knowledge, the daily
log, a session record, project state. Those belong in one coherent snapshot, because they
describe one unit of work. Committing each file separately produces history that is
technically complete and practically unreadable.

There is deliberately **no automatic session-end commit hook**. It would fire mid-work,
snapshot incoherent states, and change the client's behavior without being asked. The
snapshot is called at task completion instead — by whatever does the bookkeeping.

## Commands

```bash
ai-os workspace status              # tracked state + safety checks
ai-os workspace snapshot "<what the task did>"
```

History and recovery use git directly — wrapping them would add surface without adding
capability:

```bash
git -C ~/.ai-os log --oneline
git -C ~/.ai-os diff
git -C ~/.ai-os restore <path>      # undo an uncommitted edit
git -C ~/.ai-os checkout <sha> -- <path>   # recover one file from a snapshot
git -C ~/.ai-os revert <sha>        # undo a snapshot, keeping history
```

`reset --hard` is never used by AI OS tooling. `restore` and `revert` are additive and
recoverable; `reset --hard` discards work with no undo.

## Undoing versioning entirely

```bash
rm -rf ~/.ai-os/.git ~/.ai-os/.gitignore
```

Returns the workspace to an unversioned directory. No workspace data is touched.
