# Installation

Early software. `ai-os init` assumes a single-user local setup and has been exercised
against one machine. Treat it as a working sketch.

## What you are installing

Three things live in three places, and only one of them is this repository.

| | Where | Created by |
|---|---|---|
| **Public** — the software | wherever you clone it | `git clone` |
| **Private** — your data | `~/.ai-os` | `ai-os init` |
| **Runtime** — execution | `~/.ai` | set up per client; see `adapters/` |

`docs/public-private-contract.md` explains why they are separate. It is worth reading
before you run anything, because the separation is the product.

## Install

```bash
git clone <this-repo> ~/ai-os
export PATH="$HOME/ai-os/cli:$PATH"     # add to ~/.zshrc or ~/.config/fish/config.fish
```

Requirements: `bash`, `git`, `python3`. Nothing else — no package manager, no
dependencies, no build step.

## Initialize your workspace

```bash
ai-os init --dry-run     # see exactly what would happen
ai-os init               # do it
ai-os doctor             # verify the contract holds
```

`init` creates the seven workspace directories, the eight memory sections, the seven
knowledge kinds, and seeds a few starter files where nothing exists.

**It never overwrites anything.** Run it as many times as you like; the second run and the
hundredth are the same as the first. If a file it would seed already exists and differs
from the template, it says so and leaves yours alone.

It does **not** create a git repository, does **not** create a remote, does **not** copy
public skills into your workspace, and does **not** touch `~/.ai`.

Put the workspace somewhere else with `AI_OS_HOME`:

```bash
AI_OS_HOME=~/work/ai-os-data ai-os init
```

`init` refuses to initialize into the public repository or the runtime directory.

## Then

```bash
ai-os status                  # the three layers, and whether the contract holds
ai-os doctor                  # full check — reports, never repairs
ai-os privacy-scan            # is the public repo still publishable?
ai-os workspace status        # local versioning of your private data
```

Two things worth doing once:

1. **Fill in `~/.ai-os/config/privacy-terms.txt`** — your name, handles, emails,
   employers, private repository names. Without it `privacy-scan` runs generic patterns
   only and cannot catch a name or a client repo. The file stays private.

2. **Set a repo-local git identity on the public repo** if you intend to publish it. Every
   commit bakes in the committer email permanently:

   ```bash
   git -C ~/ai-os config user.email <a public address>
   ```

   `doctor` warns when this is unset. It will not set it for you, and it never touches
   your global git identity.

## Uninstalling

Delete the clone. Your workspace at `~/.ai-os` is untouched by that — it is yours, it was
never owned by the repository, and nothing in the repository is needed to read it. It is
plain Markdown and YAML on disk.
