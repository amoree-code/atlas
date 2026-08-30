---
name: project-init
description: Scaffold a new project end to end - create it under the right folder with the house stack, git, linting, env, context pack, and registry entry. Use when the user says new project, start a project, scaffold, bootstrap an app, or create an app/API.
---

# Project init

Scaffolds a project that matches the stack defaults in `~/.ai-os/config/models.yaml` (or
wherever the user records their conventions) and is registered from day one.

## 1. Settle four things first

Ask only what you can't infer, in one round:

- **Name** (kebab-case) and **location**: use the user's own folder convention if one is
  recorded in `~/.ai-os/memory/preferences/`; otherwise ask where new projects go.
- **Shape**: server-rendered/public app · SPA dashboard · API service · a paired
  frontend+backend. Ask which, or infer from the stated need.
- **Database**: ask, or use whatever default is recorded in the user's stack config.
- **Remote**: create a git host repo now, or local only.

Refuse to scaffold into a path that already exists — offer the project-register skill
instead.

## 2. Scaffold

Use the package manager and runtime version recorded in the user's stack config, if any;
otherwise ask once and don't re-ask for the rest of the session.

Then, per whatever house defaults are recorded (or ask if none are):
- a component library, if there's a UI
- one formatter only — never two competing ones
- strict type-checking if the language supports it
- boundary validation, plus a typed env module that fails fast on a missing var
- an ORM/migration tool if a database was chosen
- i18n/RTL setup now, not later, if the user's preferences call for it
- one real test, not a placeholder

## 3. Environment

Write `.env.example` with **key names and comments only**. Write the real env file with
real values only if the user supplies them — never invent, never commit. Confirm the
global gitignore covers env files.

## 4. Context pack

- `AGENTS.md` at the repo root, filled from what you just built. `AGENTS.md` is the AAIF
  standard read by most agent clients, so the project needs one file rather than one per
  tool; symlink `CLAUDE.md` to it for Claude Code's native name. Don't restate global
  defaults — record only what differs.
- A one-paragraph context note: why this project exists and where it stands. Add
  decisions/conventions/known-issues files only when there's something to put in them.

## 5. Git

```bash
git init -b main && git add -A && git commit -m "chore: initial scaffold"
```
Ask before creating a remote. **Do not push to main** unless the user's standing rule
says otherwise — the safe default is everything lands via PR.

## 6. Register

Add a row to `~/.ai-os/projects/registry.md`, status `active`, with today's date and the
real next action. Add the first tasks to `projects/tasks.md`.

## 7. Report

Path · stack · commands to run it · what still needs the user (env values, remote, first
feature). Keep it to a few lines.
