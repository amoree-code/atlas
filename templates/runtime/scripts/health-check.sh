#!/usr/bin/env bash
# Read-only workspace health check. Never modifies anything. Exit 1 if any FAIL.
set -uo pipefail
W="${AI_OS_HOME:-$HOME/.ai-os}"
fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; }

echo "== structure =="
for f in memory/MEMORY.md memory/README.md knowledge/README.md \
         projects/registry.md projects/tasks.md; do
  [ -f "$W/$f" ] && ok "$f" || bad "missing $W/$f"
done
for d in daily sessions config skills; do
  [ -d "$W/$d" ] && ok "$d/" || bad "missing $W/$d/"
done
for d in identity education career projects goals travel preferences interests; do
  [ -d "$W/memory/$d" ] && ok "memory/$d/" || bad "missing main section $W/memory/$d/"
done
for d in task-results technical-solutions decisions architecture research discoveries failures; do
  [ -d "$W/knowledge/$d" ] && ok "knowledge/$d/" || bad "missing $W/knowledge/$d/"
done

echo "== claude code (skip if not your adapter) =="
if [ -f "$HOME/.claude/settings.json" ]; then
  [ -f "$HOME/.claude/CLAUDE.md" ] && ok "global CLAUDE.md" || warn "missing ~/.claude/CLAUDE.md"
  n=$(ls -d "$HOME"/.claude/skills/*/ 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] && ok "$n skill(s) installed" || warn "no skills in ~/.claude/skills/"
  for s in "$HOME"/.claude/skills/*/; do
    [ -f "$s/SKILL.md" ] || warn "skill $(basename "$s") has no SKILL.md"
  done
  python3 -c "import json;json.load(open('$HOME/.claude/settings.json'))" 2>/dev/null \
    && ok "settings.json parses" || bad "settings.json is not valid JSON"
else
  warn "~/.claude not found — skipping Claude Code checks"
fi

echo "== scripts =="
for s in "$W"/config/scripts/*.sh; do
  [ -e "$s" ] || continue
  [ -x "$s" ] && ok "$(basename "$s") executable" || bad "$(basename "$s") not executable"
  bash -n "$s" 2>/dev/null || bad "$(basename "$s") has a syntax error"
done

echo "== graphify (optional) =="
if command -v graphify >/dev/null 2>&1; then
  ok "graphify $(graphify --version 2>/dev/null | awk '{print $2}') installed"
else
  warn "graphify not on PATH (optional; needed only for large-codebase navigation)"
fi

echo "== registry =="
if grep -oE '`~?/[^`]*`' "$W/projects/registry.md" 2>/dev/null | tr -d '`' | while read -r p; do
    expanded="${p/#\~/$HOME}"
    [ -e "$expanded" ] || echo "$p"
  done | grep -q .; then
  warn "registry references a path that does not exist — check with your own tooling"
else
  ok "all registry paths resolve (or registry has no path-shaped entries yet)"
fi

echo "== today =="
DIR="$W/daily/$(date +%Y)/$(date +%m)/$(date +%Y-%m-%d)"
[ -d "$DIR" ] && ok "daily folder for today" || warn "no daily folder for today (run day-start)"

echo "== security =="
[ -f "$HOME/.config/git/ignore" ] && grep -q '^\.env' "$HOME/.config/git/ignore" \
  && ok "global gitignore covers .env" || warn "global gitignore missing or does not cover .env"
perm=$(stat -f '%A' "$HOME/.ssh" 2>/dev/null)
[ "$perm" = "700" ] && ok "~/.ssh is 700" || warn "~/.ssh is $perm (expected 700)"
leak=$(grep -rlIE '(sk-[A-Za-z0-9]{20}|ghp_[A-Za-z0-9]{30}|AKIA[0-9A-Z]{16})' "$W" 2>/dev/null | head -3)
[ -z "$leak" ] && ok "no credential patterns in workspace" || bad "possible secret in: $leak"

echo
[ "$fail" = 0 ] && echo "workspace healthy" || echo "workspace has failures above"
exit $fail
