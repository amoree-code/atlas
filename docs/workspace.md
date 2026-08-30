# Your workspace

`~/.ai-os` is yours. AI OS writes into it at `init` and reads from it forever after; it
never owns it, never publishes it, and never overwrites what you have put there.

```
~/.ai-os/
├── config/      settings, model routing, identity, your privacy terms
├── memory/      what is true about you — 8 sections
├── knowledge/   what work taught the system — 7 kinds
├── projects/    per-project context and the registry
├── sessions/    session records
├── daily/       daily logs
└── skills/      your own skills
```

Seven directories, flat, no nesting beyond what the sections need. Set `AI_OS_HOME` to put
it somewhere else.

## Memory and knowledge are not the same thing

**Memory** is what is true about *you* — who you are, what you are working toward, how you
like to work. It changes slowly. `memory/` has eight sections: `identity`, `education`,
`career`, `projects`, `goals`, `travel`, `preferences`, `interests`.

**Knowledge** is what a *task* taught the system — a solved problem, a decision and its
alternatives, an approach that failed. It changes with every project. `knowledge/` has
seven kinds: `task-results`, `technical-solutions`, `decisions`, `architecture`,
`research`, `discoveries`, `failures`.

The test when it is ambiguous: *would this still be true if you never wrote another line
of code?* Yes → memory. No → knowledge. They are never merged. See
`docs/memory-architecture.md`.

## How the runtime reaches your memory

One canonical store, `~/.ai-os/memory`, and every client points at it.

Claude Code scopes its native memory per working directory
(`~/.claude/projects/<cwd-slug>/memory/`), which means memory written in one project is
invisible from another. The fix is a symlink per project directory, all pointing at the
single store. `ai-os doctor` verifies every one of them and fails on: a broken link, a
target outside the workspace, a link to a stale pre-cutover store, a real directory where
a link should be (that is a second, invisible memory store), a recursive link, and links
that disagree about where memory lives.

The links are **access**. The memory is still yours, still private, still outside the
public repository. See `docs/public-private-contract.md`.

## Configuration

```
AI OS defaults  <  your configuration  <  project configuration
```

Your values win over defaults; a project's win over yours.

- A future update **may add** a key you do not have.
- A future update **never changes** a key you have set.
- A key removed from the defaults is left alone. Deleting it is your call.

`ai-os doctor` reports which new default keys exist that your config lacks. It adds
nothing. There is no schema validation and no migration system yet, deliberately.

## Templates are seeds, not a sync

`ai-os init` copies a template only where nothing exists at the destination. After that,
the template and your file are two unrelated documents.

**Divergence is the expected steady state, not a defect.** Once you edit a seeded file it
is yours. Changing a template in the public repository has no effect on any existing
workspace, and nothing ever reapplies one over your version. `init` reports which files
differ so you can look; it will not act.

Runtime scripts are *not* seeded into your workspace — they belong to the runtime layer.
(Earlier versions seeded them into `config/scripts/`, which created a second copy nothing
ever read. Fixed in V0.1.3.)

## Skills: yours win

```
resolution order:  ~/.ai-os/skills   →   <ai-os>/skills
```

Public skills stay in the public repository. They are **not** copied into your workspace
at init — copying would turn software into your files and make it impossible to update.
When a skill name exists in both places, **yours wins**, and nothing will ever overwrite,
modify or delete it. `ai-os doctor` lists which of your skills are shadowing a public one.

## Versioning — local only

The workspace is a git repository with **no remote, and it must stay that way.** Local git
gives you history, rollback and audit. That is not publishing.

```bash
ai-os workspace status     # tracked state plus the safety checks
ai-os workspace snapshot   # one commit per completed task, not per file edit
git -C ~/.ai-os log        # history
git -C ~/.ai-os diff       # what changed
git -C ~/.ai-os restore <path>
```

A `pre-push` hook refuses pushes; a `pre-commit` hook blocks credential-shaped strings
from entering history at all — a local commit is still a permanent record. `ai-os init`
never creates the repository and never creates a remote. See
`docs/workspace-versioning.md`.

## Privacy terms

`config/privacy-terms.txt` holds your identifying strings — name, handles, emails,
employers, private repository names. `ai-os privacy-scan` uses them to check that the
public repository contains none of them.

They live here, not in the public repository, for a reason: **a scanner that hardcoded
your real name and employer would itself be the leak it exists to prevent.** The public
half ships only generic shapes. Without this file the scan still runs, but only on those
generic patterns — names and repository names are not checked, and `doctor` warns you.
