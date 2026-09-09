# Safety

The everyday guards for a workspace that holds real personal data: keeping it versioned
without publishing it, and keeping the public repository free of what leaked into it by
accident. The reasoning behind these guards is in `docs/design/public-private.md`.

## Versioning your workspace

```bash
atlas workspace status              # tracked state + safety checks
atlas workspace snapshot "<what the task did>"
```

`atlas init` does not create a git repository or a remote — that is your call. If you run
`git init` in `$ATLAS_HOME` yourself, the one rule is **no remote, ever**. History and
recovery use git directly:

```bash
git -C ~/atlas log --oneline
git -C ~/atlas diff
git -C ~/atlas restore <path>              # undo an uncommitted edit
git -C ~/atlas checkout <sha> -- <path>    # recover one file from a snapshot
git -C ~/atlas revert <sha>                # undo a snapshot, keeping history
```

`reset --hard` is never used by Atlas tooling. `restore` and `revert` are additive and
recoverable; `reset --hard` discards work with no undo.

**Snapshot model:** one commit per completed task, not per file write. A finished task
typically touches several areas at once — memory, knowledge, the daily log, a session
record, project state — and those belong in one coherent commit rather than several
technically-complete, practically-unreadable ones. There is deliberately no automatic
session-end commit hook: it would fire mid-work and snapshot an incoherent state.

**Undoing versioning entirely** returns the workspace to an unversioned directory. No
workspace data is touched:

```bash
rm -rf ~/atlas/.git ~/atlas/.gitignore
```

## The guards, and what each is actually worth

| Guard | Catches | Honest limit |
|---|---|---|
| **No remote configured** | everything — there is nowhere to push | someone can add one |
| `pre-push` hook | a push after a remote was added | `--no-verify` bypasses it — **and you must write the hook: none ships here** |
| `pre-commit` hook | credential-shaped strings entering history | pattern-based, not PII-aware by design — **and you must write the hook: none ships here** |
| Agent-level command guard | an agent running push/remote commands | adapter-specific |
| `atlas workspace status` | remotes, nested repos, missing hooks | reports; does not block |

Only the first is a guarantee. The rest are defense-in-depth: they turn a silent accident
into a loud one. Treat the hooks as smoke alarms, not locks — this repository ships
neither hook body nor an installer, so a report that one is missing describes your setup,
not a defect in the tooling.

The `pre-commit` hook, if you write one, should scan for **credentials, not personal
information**. Personal data is the intended content of the workspace; blocking it would
make the workspace useless. Credentials have no reason to be there at all.

## Nested repositories are a defect, not a setting

The public repository and the private workspace must never contain one another. When
tooling finds a nested repository it **reports it loudly**; it never adds it to
`.gitignore` — hiding the problem would leave it in place while making it invisible,
which is strictly worse.

## Keeping the public repository publishable

```bash
atlas privacy-scan            # is this repository still publishable?
atlas privacy-scan docs       # the same check, scoped to docs/
```

Fill in `~/atlas/internal/governance/policies/privacy-terms.txt` with your name, handles, emails,
employers and private repository names once, early. Without it `privacy-scan` runs only
generic patterns and cannot catch a name or a client repository — the file itself stays
private and is never read by anything in the public repository.

A `git push` from the public repository requires explicit approval every time; see
`internal/governance/policies/git.yaml` and `docs/design/governance.md`.
