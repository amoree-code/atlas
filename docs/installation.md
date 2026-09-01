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
public skills into your workspace, and does **not** touch `~/.ai`. It also asks you
nothing — that is `ai-os onboard`, below.

Put the workspace somewhere else with `AI_OS_HOME`:

```bash
AI_OS_HOME=~/work/ai-os-data ai-os init
```

`init` refuses to initialize into the public repository or the runtime directory.

## Set yourself up

`init` builds the structure. It deliberately asks nothing — a workspace that exists is not
the same as a workspace that knows who you are, and conflating the two is how a setup ends
up claiming an identity it never collected.

```bash
ai-os onboard            # first run: a few questions, then it validates and marks done
ai-os onboard status     # has this workspace completed onboarding?
```

Onboarding asks for the minimum — what to call you, what languages you work in, what to
reply in — and detects the rest (OS, shell, home, installed AI clients, tooling) rather
than asking. Everything beyond that is optional and skippable.

Where the answers go is the important part. Onboarding is **not** a second profile system:
each answer is written to the one canonical owner for that fact and nowhere else.

| Answer | Canonical owner |
|---|---|
| name, languages | `user/02-personal/memory/identity/` |
| reply language | `user/02-personal/memory/preferences/` |
| what you work on | `user/02-personal/memory/career/` |
| code root, VCS account | `system/config/profile.yaml` |
| *whether onboarding is done* | `system/config/workspace.yaml` |

`workspace.yaml` holds state and pointers. It never holds a copy of a fact that lives
somewhere else.

**Already have a populated workspace?** Adopt it instead of answering questions you have
already answered:

```bash
ai-os onboard --adopt    # records that setup is done; writes no memory file
```

**Interrupted halfway?** Run `ai-os onboard` again. Answered steps are skipped; it resumes
at the first unanswered one. Completed onboarding never re-runs the interview.

**Driving it from an AI client, or a script?** The same primitives, non-interactively:

```bash
ai-os onboard set name "<your name>"
ai-os onboard set language "<language>"
ai-os onboard complete
```

`complete` validates before it marks anything — required answers recorded, canonical files
actually on disk, workspace structure sound. If a check fails it says so and leaves the
state alone.

If the marker ever claims `initialized` while the data it points at is gone, `status`
reports `inconsistent` and exits 12 rather than assuming either side is right.
`ai-os onboard --repair` reopens only the missing steps and touches nothing that survived.

## Then

```bash
ai-os status                  # the three layers, and whether the contract holds
ai-os doctor                  # full check — reports, never repairs
ai-os privacy-scan            # is the public repo still publishable?
ai-os workspace status        # local versioning of your private data
```

Two things worth doing once:

1. **Fill in `~/.ai-os/system/policies/privacy-terms.txt`** — your name, handles, emails,
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
