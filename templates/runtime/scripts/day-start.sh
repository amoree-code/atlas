#!/usr/bin/env bash
# Create today's daily folder and seed brief/plan/log from templates.
# Idempotent: never overwrites an existing file. Prints the folder path.
set -euo pipefail
W="${AI_OS_HOME:-$HOME/.ai-os}"
D=$(date +%Y-%m-%d)
# daily/ is mid-migration. This script cannot call cli/ai-os-paths — the resolver lives in
# the public repository and this script knows only its own workspace — so it repeats the
# resolver's rule in the smallest form: the new name when it exists, else the old one,
# which is still what `ai-os init` creates. Creating the wrong one would split today's
# notes across two stores.
if [ -d "$W/personal/daily" ]; then DAILY="$W/personal/daily"; else DAILY="$W/user/01-daily"; fi
DIR="$DAILY/$(date +%Y)/$(date +%m)/$D"
mkdir -p "$DIR"

[ -f "$DIR/brief.md" ] || cat > "$DIR/brief.md" <<EOF
# Brief — $D

*Under a minute to read. Filled in via the day-start skill.*

## Focus today

## Active projects

## Unfinished from last session

## Reminders
EOF

[ -f "$DIR/plan.md" ] || cat > "$DIR/plan.md" <<EOF
# Plan — $D

## P1

## P2

## P3

## Optional

## Blockers

## Carry-over
EOF

[ -f "$DIR/log.md" ] || printf '# Log — %s\n\nMeaningful events only: decisions, completions, problems, solutions, discoveries.\n\n' "$D" > "$DIR/log.md"

echo "$DIR"
