# Getting started

The fast path. Each step links to where to go deeper.

## 1. Install

```bash
git clone <this-repo> ~/ai-os
export PATH="$HOME/ai-os/cli:$PATH"     # add to ~/.zshrc or ~/.config/fish/config.fish
```

Requires `bash`, `git`, `python3`. Nothing else — no package manager, no dependencies, no
build step. Full walkthrough, including moving the workspace off the default path: `docs/use/install.md`.

## 2. Create your workspace

```bash
ai-os init --dry-run     # see exactly what would happen
ai-os init               # create ~/.ai-os — never overwrites anything
ai-os doctor             # verify the contract holds
```

What gets created and why it's shaped the way it is: `docs/use/workspace.md` and
`docs/design/workspace-structure.md`.

## 3. Tell it who you are (optional, but worth doing once)

```bash
ai-os onboard
```

A few questions, written to their one canonical owner each — no second profile system.
Already have a populated workspace? `ai-os onboard --adopt` instead. Detail: `docs/use/install.md`.

## 4. Know the boundary

AI OS is two layers: this repository (public, reusable, publishable) and your workspace
(`$AI_OS_HOME`, private, never published). `ai-os doctor` checks the boundary holds on
every run. The full contract: `docs/design/public-private.md`.

## 5. Pick a client

An **adapter** connects one AI client (Claude Code, Codex, Cursor, Gemini, OpenCode) to AI
OS. `docs/use/adapters.md` lists what each one does today.

## 6. See what AI OS can actually do

- **Capabilities** — what AI OS can *do* (browser control ships today): `docs/use/capabilities.md`.
- **Domains** — declaring an area of work, which executes nothing: `docs/use/domains.md`.

## Where to read next

`docs/README.md` is the full reading order. `docs/use/safety.md` covers versioning your
workspace and keeping the public repository publishable — worth reading before you commit
anything to either.
