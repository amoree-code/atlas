#!/bin/sh
# Read-only. Prints the state Claude needs to resume work cold.
set -u

ROOT="${OCEAN_ROOT:-$HOME/ocean}"
# Record areas sit at the root, or under brain/ before the T-243 layout move.
BRAIN="$ROOT"
if [ ! -d "$ROOT/04-projects" ] && [ -d "$ROOT/brain/04-projects" ]; then BRAIN="$ROOT/brain"; fi
D=$(date +%Y-%m-%d)
FILE="$BRAIN/01-daily/$D.md"

echo "=== today: $D ==="
if [ -f "$FILE" ]; then echo "daily record: $FILE"; else echo "daily record: NOT CREATED (run day-start.sh)"; fi

echo
echo "=== ocean context ==="
ocean context 2>/dev/null

echo
echo "=== last 3 sessions ==="
ocean session list 2>/dev/null | jq -r '.[0:3][] | "\(.updatedAt)  \(.status)  \(.title)  next: \(.nextAction // "-")"' 2>/dev/null \
  || echo "(none yet, or ocean session list unavailable)"

echo
echo "=== active/blocked tasks ==="
found=0
for state in active blocked; do
  count=$(ocean tasks list "$state" 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
  if [ "$count" != "0" ]; then
    ocean tasks list "$state" 2>/dev/null | jq -r --arg st "$state" '.[] | "  \(.id)  \($st)  \(.project)  \(.title)"'
    found=1
  fi
done
[ "$found" = 0 ] && echo "  (none — see ocean tasks list)"

echo
echo "=== registry active rows ==="
REG="$BRAIN/04-projects/registry.md"
[ -f "$REG" ] && grep -E '^\| \*\*' "$REG" | grep 'active' || echo "(registry.md not found or no active rows)"

echo
echo "=== repos with uncommitted work ==="
find "$HOME/Documents" -maxdepth 6 -type d -name .git -not -path "*/node_modules/*" 2>/dev/null | sed 's|/.git$||' | while read -r p; do
  n=$(git -C "$p" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  b=$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ "$n" != "0" ] && printf '  %-34s %-28s %s file(s)\n' "$(basename "$p")" "$b" "$n"
done
exit 0
