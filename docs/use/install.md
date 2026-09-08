# Installation

Early software. `atlas init` assumes a single-user local setup and has been exercised
against one machine. Treat it as a working sketch.

**Naming note (T-031):** `atlas` is the canonical command; `atlas` remains a temporary
compatibility alias that resolves identically during the transition window. Examples
below use `atlas`; anywhere you read `atlas`, it still works the same way.

## What you are installing

Two things live in two places, and only one of them is this repository.

| | Where | Created by |
|---|---|---|
| **Public** — the software | wherever you clone it | `git clone` |
| **Private** — your data | `$ATLAS_HOME`, default `~/atlas` | `atlas init` |

Compatibility fallback: `$ATLAS_HOME`, default `~/atlas`, still resolves for any root Atlas
does not yet hold — see `cli/atlas-paths`. Atlas is never bypassed when it already has the
requested resource.

Client integration is not a third place: each client reaches Atlas through its adapter in
`adapters/<client>/`, which is public software like the rest of the repository.

`docs/design/public-private.md` explains why the two are separate. It is worth reading
before you run anything, because the separation is the product.

## Install

```bash
git clone <this-repo> ~/atlas
export PATH="$HOME/atlas/cli:$PATH"     # add to ~/.zshrc or ~/.config/fish/config.fish
```

Requirements: `bash`, `git`, `python3`. Nothing else — no package manager, no
dependencies, no build step.

## Initialize your workspace

```bash
atlas init --dry-run     # see exactly what would happen
atlas init               # do it
atlas doctor             # verify the contract holds
```

`init` creates the seven workspace directories, the eight memory sections, the seven
knowledge kinds, and seeds a few starter files where nothing exists.

**It never overwrites anything.** Run it as many times as you like; the second run and the
hundredth are the same as the first. If a file it would seed already exists and differs
from the template, it says so and leaves yours alone.

It does **not** create a git repository, does **not** create a remote, and does **not**
copy public skills into your workspace. It also asks you nothing — that is `atlas
onboard`, below.

Put the workspace somewhere else with `ATLAS_HOME` (or, as a compatibility fallback,
`ATLAS_HOME` for roots Atlas has not cut over):

```bash
ATLAS_HOME=~/work/atlas-data atlas init
```

`init` refuses to initialize into the public repository, or into the retired `~/.ai`
location.

## Set yourself up

`init` builds the structure. It deliberately asks nothing — a workspace that exists is not
the same as a workspace that knows who you are, and conflating the two is how a setup ends
up claiming an identity it never collected.

```bash
atlas onboard            # first run: a few questions, then it validates and marks done
atlas onboard status     # has this workspace completed onboarding?
```

Onboarding asks for the minimum — what to call you, what languages you work in, what to
reply in — and detects the rest (OS, shell, home, installed AI clients, tooling) rather
than asking. Everything beyond that is optional and skippable.

Where the answers go is the important part. Onboarding is **not** a second profile system:
each answer is written to the one canonical owner for that fact and nowhere else.

| Answer | Canonical owner |
|---|---|
| name, languages | `personal/memory/identity/` |
| reply language | `personal/memory/preferences/` |
| what you work on | `personal/memory/career/` |
| code root, VCS account | `internal/config/profile.yaml` |
| *whether onboarding is done* | `internal/config/workspace.yaml` |

`workspace.yaml` holds state and pointers. It never holds a copy of a fact that lives
somewhere else.

**Already have a populated workspace?** Adopt it instead of answering questions you have
already answered:

```bash
atlas onboard --adopt    # records that setup is done; writes no memory file
```

**Interrupted halfway?** Run `atlas onboard` again. Answered steps are skipped; it resumes
at the first unanswered one. Completed onboarding never re-runs the interview.

**Driving it from an AI client, or a script?** The same primitives, non-interactively:

```bash
atlas onboard set name "<your name>"
atlas onboard set language "<language>"
atlas onboard complete
```

`complete` validates before it marks anything — required answers recorded, canonical files
actually on disk, workspace structure sound. If a check fails it says so and leaves the
state alone.

If the marker ever claims `initialized` while the data it points at is gone, `status`
reports `inconsistent` and exits 12 rather than assuming either side is right.
`atlas onboard --repair` reopens only the missing steps and touches nothing that survived.

## Then

```bash
atlas status                  # where each layer is, and whether the contract holds
atlas doctor                  # full check — reports, never repairs
atlas privacy-scan            # is the public repo still publishable?
atlas workspace status        # local versioning of your private data
```

Two things worth doing once:

1. **Fill in `~/atlas/internal/governance/policies/privacy-terms.txt`** — your name, handles, emails,
   employers, private repository names. Without it `privacy-scan` runs generic patterns
   only and cannot catch a name or a client repo. The file stays private.

2. **Set a repo-local git identity on the public repo** if you intend to publish it. Every
   commit bakes in the committer email permanently:

   ```bash
   git -C ~/atlas config user.email <a public address>
   ```

   `doctor` warns when this is unset. It will not set it for you, and it never touches
   your global git identity.

## Uninstalling

Delete the clone. Your workspace at `~/atlas` (compatibility fallback: `~/atlas`) is untouched by that — it is yours, it was
never owned by the repository, and nothing in the repository is needed to read it. It is
plain Markdown and YAML on disk.
