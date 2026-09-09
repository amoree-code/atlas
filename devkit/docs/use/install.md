# Installation and onboarding

Atlas has a public engine and a separate private workspace. Keep those locations separate:

| Layer | Location | Contains |
|---|---|---|
| Public engine | any clone location | reusable code and documentation |
| Private workspace | `$ATLAS_HOME` (default `~/atlas`) | personal data and local runtime state |

## Install the engine

```bash
git clone https://github.com/amoree-code/atlas.git atlas
cd atlas
export PATH="$PWD/cli:$PATH"
```

Requirements: `bash`, `git`, and `python3`.

## Recommended setup

Preview the first-run plan, then approve it:

```bash
atlas setup preflight
atlas setup apply --approve
```

The approved flow initializes the private workspace, verifies or adopts its structure,
inspects adapters, runs onboarding when needed, and finishes with health checks. It does
not publish, push, merge, or install external tools.

For an interactive walkthrough, run `atlas setup` and follow the prompts.

## Custom workspace location

Set `ATLAS_HOME` before setup when private data should live elsewhere:

```bash
ATLAS_HOME="$HOME/work/atlas-data" atlas setup
ATLAS_HOME="$HOME/work/atlas-data" atlas setup apply --approve
```

The workspace must not be the public engine clone and must not be the retired `~/.ai`
location. `atlas root` and `atlas status` show which paths are active.

## Onboarding

Onboarding stores identity and preferences in their canonical private locations:

```bash
atlas onboard
atlas onboard status
atlas onboard --adopt
```

Use `--adopt` when the workspace already contains the information and you only need to
record that onboarding is complete. Use `atlas onboard --repair` when status reports an
inconsistent marker.

## Verify and maintain

```bash
atlas status
atlas doctor
atlas privacy-scan
atlas docs check
atlas adapter doctor
atlas capability doctor
```

`doctor` and `privacy-scan` report; they do not repair or publish anything. Optional
capabilities may report unavailable when their external executable is not installed.

## Uninstall

Removing the public clone does not remove the private workspace. If you later remove the
private workspace, first back it up and confirm the exact path; Atlas does not provide a
destructive uninstall command.
