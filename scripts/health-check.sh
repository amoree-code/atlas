#!/bin/sh
set -eu

ROOT="${OCEAN_ROOT:-${ATLAS_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)}}"
failures=0
check_dir() { if [ -d "$ROOT/$1" ]; then printf 'OK: %s\n' "$1"; else printf 'FAIL: missing directory %s\n' "$1"; failures=$((failures + 1)); fi; }
check_file() { if [ -f "$ROOT/$1" ]; then printf 'OK: %s\n' "$1"; else printf 'FAIL: missing file %s\n' "$1"; failures=$((failures + 1)); fi; }
for item in kernel/bridge/config kernel/bridge/registry kernel/bridge/integrations kernel/bridge/profiles kernel/bridge/runtime kernel/bridge/sessions kernel/bridge/archive; do check_dir "$item"; done
for item in kernel/bridge/SYSTEM.md kernel/bridge/config/CONFIG.md kernel/bridge/integrations/INTEGRATIONS.md kernel/bridge/profiles/PROFILES.md kernel/bridge/runtime/RUNTIME.md kernel/bridge/sessions/SESSIONS.md kernel/bridge/sessions/sessions.sqlite kernel/bridge/runtime/shims/atlas; do check_file "$item"; done
if [ -x "$ROOT/kernel/bridge/runtime/shims/atlas" ]; then printf 'OK: atlas shim executable\n'; else printf 'FAIL: atlas shim is not executable\n'; failures=$((failures + 1)); fi
if find "$ROOT/kernel/bridge" -path "$ROOT/kernel/bridge/archive" -prune -o -name '.env*' -print | grep -q .; then printf 'FAIL: environment file in active system\n'; failures=$((failures + 1)); else printf 'OK: no active environment files\n'; fi
if [ "$failures" -gt 0 ]; then printf 'NOT READY: %s system checks failed\n' "$failures"; exit 1; fi
printf 'PROVEN: system health checks passed\n'
