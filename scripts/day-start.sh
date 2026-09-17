#!/bin/sh
# Create today's daily record if it doesn't exist. Idempotent: never overwrites.
# Prints the file path. Format: one flat file per date (see personal/README.md).
set -eu

ROOT="${ATLAS_ROOT:-$HOME/atlas}"
D=$(date +%Y-%m-%d)
FILE="$ROOT/personal/daily/$D.md"

if [ ! -f "$FILE" ]; then
  cat > "$FILE" <<EOF
# Daily — $D

## Focus

## Work log

## Decisions

## Problems

## Next
EOF
fi

echo "$FILE"
