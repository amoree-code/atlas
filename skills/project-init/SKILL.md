---
name: project-init
description: Scaffold a new project end to end - create it under the right org folder with the house stack, git, linting, env, context pack, and registry entry. Use when the user says new project, start a project, scaffold, bootstrap an app, or create a Next.js/NestJS project.
---

# Project init

Scaffolds a project that matches the house defaults in
`{{profile.stack.doc}}` and is registered from day one.

## 1. Settle four things first

Ask only what you can't infer, in one round:

- **Name** (kebab-case) and **org folder**: `{{profile.code_root}}/{{{profile.project_roots.orgs}}}/`.
  Personal products go to `{{profile.project_roots.personal_subdir}}/`, freelance to `{{profile.project_roots.freelance_subdir}}/`.
- **Shape**: Next.js app · React+Vite SPA · NestJS API · Next.js + NestJS pair.
  Default by need: SSR/SEO/public → Next.js. Authenticated dashboard → Vite SPA.
- **Database**: Postgres+Prisma (default), Supabase, or none.
- **Remote**: create a GitHub repo now, or local only.

Refuse to scaffold into a path that already exists — offer `/project-register` instead.

## 2. Scaffold

Use **pnpm** and **Node 22** throughout. Write a `.node-version` file containing `22`.

```bash
# Next.js
pnpm create next-app@latest <name> --ts --tailwind --eslint --app --src-dir --import-alias "@/*"
# React SPA
pnpm create vite@latest <name> -- --template react-ts
# NestJS
pnpm dlx @nestjs/cli new <name> --package-manager pnpm
```

Then, per the house defaults:
- shadcn/ui if there's a UI: `pnpm dlx shadcn@latest init`
- Prettier + `eslint-config-prettier` (one formatter only — never two competing)
- `tsconfig.json`: `"strict": true`
- Zod for boundary validation, plus a typed env module that fails fast on a missing var
- TanStack Query for server state, if the UI talks to an API
- Prisma if Postgres: `pnpm dlx prisma init`
- Dashboards: set up i18n and RTL now, not later (see `memory/identity.md`)
- Vitest for a Vite/Next app; Jest ships with NestJS. Add one real test, not a placeholder.

## 3. Environment

Write `.env.example` with **key names and comments only**. Write `.env.local` (or `.env`)
with real values only if the user supplies them — never invent, never commit. Confirm
the global gitignore covers `.env*`.

## 4. Context pack

- `AGENTS.md` at the repo root from `{{profile.templates_dir}}/project-claude.md` (template — unmoved),
  filled from what you just built, then `ln -s AGENTS.md CLAUDE.md`. `AGENTS.md` is the
  AAIF standard every installed agent reads; the symlink gives Claude its native name
  from the same file, so there is nothing to keep in sync. Don't restate the global defaults — record only what
  differs.
- `{{client.project_memory}}context.md` — one paragraph: why this project exists and where it stands.
  Create `decisions.md`, `conventions.md`, `known-issues.md` only when there's something
  to put in them.

## 5. Git

```bash
git init -b main && git add -A && git commit -m "chore: initial scaffold"
```
Ask before creating a remote. If yes: `gh repo create <name> --private --source=. --remote=origin`.
**Do not push to main** — the standing rule is that everything lands via PR.

## 6. Register

Add a row to `~/.ai-os/projects/registry.md` under the right org, status
`active`, with today's date and the real next action. Add the first tasks to
`projects/tasks.md`.

## 7. Report

Path · stack · commands to run it · what still needs the user (env values, remote,
first feature). Keep it to a few lines.
