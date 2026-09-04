#!/usr/bin/env bash
# Read-only. Prints the state the agent needs to resume work cold.
set -uo pipefail
W="${AI_OS_HOME:-$HOME/.ai-os}"
D=$(date +%Y-%m-%d)
DAILY="$W/personal/daily"
PROJECTS="$W/projects"
DIR="$DAILY/$(date +%Y)/$(date +%m)/$D"

echo "=== today: $D ==="
if [ -d "$DIR" ]; then echo "daily folder: $DIR"; else echo "daily folder: NOT CREATED (run day-start.sh)"; fi

echo
echo "=== last 3 session records ==="
ls -t "$W"/internal/sessions/*/*/*.md 2>/dev/null | head -3 | while read -r f; do
  echo "--- ${f#$W/internal/sessions/}"
  sed -n '1,12p' "$f" | sed 's/^/    /'
done
[ -z "$(ls -t "$W"/internal/sessions/*/*/*.md 2>/dev/null)" ] && echo "(none yet)"

echo
echo "=== open tasks ==="
grep -E '^\- \[(TODO|WIP|BLOCKED)\]' "$PROJECTS/tasks.md" 2>/dev/null || echo "(none)"

echo
echo "=== repos with uncommitted work ==="
find "$HOME/Documents" -maxdepth 6 -type d -name .git -not -path "*/node_modules/*" 2>/dev/null | sed 's|/.git$||' | while read -r p; do
  n=$(git -C "$p" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  b=$(git -C "$p" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ "$n" != "0" ] && printf '  %-34s %-28s %s file(s)\n' "$(basename "$p")" "$b" "$n"
done
exit 0
