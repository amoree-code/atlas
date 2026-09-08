#!/usr/bin/env bash
# Create today's daily folder and seed brief/plan/log from templates.
# Idempotent: never overwrites an existing file. Prints the folder path.
set -euo pipefail
W="${ATLAS_HOME:-$HOME/atlas}"
D=$(date +%Y-%m-%d)
DAILY="$W/personal/daily"
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
