---
name: project-register
description: Adopt an existing repository into the workspace - analyze it, write its context files, and add it to the registry without changing any code. Use when the user says register this project, adopt this repo, add to registry, or set up context for this project.
---

# Project register

Give an existing repo a context pack. **Never restructure, rename, move, reformat, or
"improve" the code.** Analysis and documentation only.

## 1. Analyze

Read, don't guess:
```bash
git -C <repo> remote -v; git -C <repo> log --oneline -15
git -C <repo> branch -a; git -C <repo> status --short
cat <repo>/package.json          # or requirements.txt / pyproject.toml / go.mod
ls <repo>/src <repo>/app 2>/dev/null
cat <repo>/README.md 2>/dev/null
ls -a <repo> | grep -E 'env|config|docker|CI'
```
Then read enough source to state the architecture truthfully — entry point, routing,
state, data access. If you can't tell, write "unclear" rather than a plausible guess.

For env: list **key names only**, from `.env.example` or by grepping variable names.
**Never read or record a value.**

## 2. Write the context pack

- `<repo>/AGENTS.md` — the AAIF standard read by most agent clients, so the project needs
  one file rather than one per tool. Symlink `CLAUDE.md` to it for Claude Code's native
  name: one file on disk, both names, nothing to keep in sync. Commands must come from
  the repo's real scripts/tasks. Record only what differs from the user's own recorded
  stack conventions — if nothing differs, say so.
- `<repo>/.claude/memory/context.md` (or your client's equivalent) — what it is, who it
  serves, where it stands, what's in flight (name the branch and uncommitted work if any).
- A known-issues note only if the analysis turned up real gotchas.

## 3. Keep it out of shared repos

If the remote doesn't belong to an account the user owns, the context is personal —
don't commit it:
```bash
printf 'CLAUDE.md\n.claude/\n' >> <repo>/.git/info/exclude
```
`.git/info/exclude` is local-only and never travels to the remote. For the user's own
repos, leave the files committable and mention it.

## 4. Build a code graph — only if the repo is large

Count first: `find <repo>/src -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.py' \) | wc -l`

**Under ~150 source files: skip this.** Reading files directly is faster and cheaper.
At ~150+ files, use whatever local code-graph tool is configured (see its own skill/docs
for the exact invocation) — with any local-only / no-external-API flag it offers.

## 5. Register

Add or update the row in `~/.ai-os/projects/registry.md`: path, stack, repo, status,
last commit date, real next action. Add any obvious follow-ups to `projects/tasks.md`.

## 6. Report

What it is, its actual state (branch, uncommitted files, staleness), anything that looked
wrong, and the files you created. Flag rather than fix.
