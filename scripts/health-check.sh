#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
failures=0
check_dir() { if [ -d "$ROOT/$1" ]; then printf 'OK: %s\n' "$1"; else printf 'FAIL: missing directory %s\n' "$1"; failures=$((failures + 1)); fi; }
check_file() { if [ -f "$ROOT/$1" ]; then printf 'OK: %s\n' "$1"; else printf 'FAIL: missing file %s\n' "$1"; failures=$((failures + 1)); fi; }
for item in system/config system/control-plane system/integrations system/profiles system/runtime system/sessions system/archive; do check_dir "$item"; done
for item in system/SYSTEM.md system/config/CONFIG.md system/control-plane/CONTROL-PLANE.md system/integrations/INTEGRATIONS.md system/profiles/PROFILES.md system/runtime/RUNTIME.md system/sessions/SESSIONS.md system/sessions/sessions.sqlite system/runtime/shims/atlas; do check_file "$item"; done
if [ -x "$ROOT/system/runtime/shims/atlas" ]; then printf 'OK: atlas shim executable\n'; else printf 'FAIL: atlas shim is not executable\n'; failures=$((failures + 1)); fi
if find "$ROOT/system" -path "$ROOT/system/archive" -prune -o -name '.env*' -print | grep -q .; then printf 'FAIL: environment file in active system\n'; failures=$((failures + 1)); else printf 'OK: no active environment files\n'; fi
if [ "$failures" -gt 0 ]; then printf 'NOT READY: %s system checks failed\n' "$failures"; exit 1; fi
printf 'PROVEN: system health checks passed\n'
