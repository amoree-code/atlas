---
name: project-register
description: Adopt an existing repository into the workspace - analyze it, write its CLAUDE.md and memory, and add it to the registry without changing any code. Use when the user says register this project, adopt this repo, add to registry, or set up context for this project.
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

For env: list **key names only**, from `.env.example` or by `grep -oE` on variable names.
**Never read or record a value.**

## 2. Write the context pack

- `<repo>/AGENTS.md` from `{{profile.templates_dir}}/project-claude.md` (template —
  unmoved). **Use `AGENTS.md`, not `{{client.project_context}}`** — it is the AAIF standard read by Claude
  Code, Codex, Cursor, Gemini, and opencode alike, so the project needs one file rather
  than one per tool. Then `ln -s AGENTS.md CLAUDE.md` so Claude's native name resolves to
  the same file: one file on disk, both names, nothing to keep in sync.
  Commands must come from the real `scripts` block. Conventions section records only what
  differs from `{{profile.stack.doc}}` — if nothing differs, say so.
- `<repo>/{{client.project_memory}}context.md` — what it is, who it serves, where it stands, what's
  in flight (name the branch and uncommitted work if any).
- `known-issues.md` if the analysis turned up real gotchas. Otherwise skip it.

## 3. Keep it out of shared repos

If the remote is **not** under `{{profile.vcs_owner}}`, the context is personal — don't commit it:
```bash
printf 'CLAUDE.md\n.claude/\n' >> <repo>/.git/info/exclude
```
`.git/info/exclude` is local-only and never travels to the remote. For the user's own
repos, leave the files committable and mention it.

## 4. Build a code graph — only if the repo is large

Count first: `find <repo>/src -type f \( -name '*.ts' -o -name '*.tsx' -o -name '*.js' -o -name '*.py' \) | wc -l`

**Under ~150 source files: skip this.** Reading files directly is faster and cheaper.

At ~150+ files, from the repo root:
```bash
graphify ./src --code-only --out .
```
`--code-only` is **mandatory** — the default mode sends docs, PDFs, and images to an
external LLM API. `--code-only` is pure local AST: no key, no network.

`{{profile.code_graph.output}}` is covered by the global gitignore. Note in `{{client.project_context}}` that the graph
exists and must be rebuilt after significant changes (`graphify ./src --code-only --out . --update`).

## 5. Register

Add or update the row in `~/.ai-os/user/04-projects/registry.md`: path, stack, repo,
status, last commit date, real next action. Add any obvious follow-ups to
`~/.ai-os/user/04-projects/tasks.md`.

If the analysis produced project-local state worth keeping — standing decisions,
domain knowledge, operating rules — create `~/.ai-os/user/04-projects/<project>/` with
only the parts that have content (`memory/`, `rules/`, `knowledge/`, `context/`, per
its README). Do not scaffold empty directories, and never copy global memory into it.

## 6. Report

What it is, its actual state (branch, uncommitted files, staleness), anything that looked
wrong, and the files you created. Flag rather than fix.
