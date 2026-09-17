#!/bin/sh
# Read-only. Prints the state Claude needs to resume work cold.
set -u

ROOT="${ATLAS_ROOT:-$HOME/atlas}"
D=$(date +%Y-%m-%d)
FILE="$ROOT/personal/daily/$D.md"

echo "=== today: $D ==="
if [ -f "$FILE" ]; then echo "daily record: $FILE"; else echo "daily record: NOT CREATED (run day-start.sh)"; fi

echo
echo "=== atlas context ==="
atlas context 2>/dev/null

echo
echo "=== last 3 sessions ==="
atlas session list 2>/dev/null | jq -r '.[0:3][] | "\(.updatedAt)  \(.status)  \(.title)  next: \(.nextAction // "-")"' 2>/dev/null \
  || echo "(none yet, or atlas session list unavailable)"

echo
echo "=== active/blocked tickets ==="
found=0
for state in active blocked; do
  count=$(atlas tickets list "$state" 2>/dev/null | jq 'length' 2>/dev/null || echo 0)
  if [ "$count" != "0" ]; then
    atlas tickets list "$state" 2>/dev/null | jq -r --arg st "$state" '.[] | "  \(.id)  \($st)  \(.project)  \(.title)"'
    found=1
  fi
done
[ "$found" = 0 ] && echo "  (none — see atlas tickets list)"

echo
echo "=== registry active rows ==="
REG="$ROOT/projects/registry.md"
[ -f "$REG" ] && grep -E '^\| \*\*' "$REG" | grep 'active' || echo "(registry.md not found or no active rows)"

echo
echo "=== repos with uncommitted work ==="
find "$HOME/Documents" -maxdepth 6 -type d -name .git -not -path "*/node_modules/*" 2>/dev/null | sed 's|/.git$||' | while read -r p; do
  n=$(git -C "$p" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  b=$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ "$n" != "0" ] && printf '  %-34s %-28s %s file(s)\n' "$(basename "$p")" "$b" "$n"
done
exit 0
