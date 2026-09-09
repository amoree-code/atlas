#!/usr/bin/env python3
"""tests/test-cli-source-drift.py — T-025, retired by T-118.

T-025's original concern was two physical trees existing by design (`<repo>/cli/` and
`~/atlas/`), a consequence of the migration cutting commands over one at a time
(T-016/017/018 moved `context`/`usage`/`lifecycle`/`observe`; T-012 placed, but explicitly
did not cut over, everything else). That transition state ended with T-118: the
`~/atlas/context/` dispatch mirror and the `~/atlas/core/cli/` copies (both the
context/usage/lifecycle/observe family and the mission/coordinator "core vs engine" parity
subsystem — atlas-mission, atlas-coordinator, atlas-handoff, atlas_mission.py,
atlas_coordination.py, atlas_context_packet.py) were retired outright: `core/cli/` no longer
exists on disk at all (see test-context-parity.py's and test-mission-*.py's retirement
notes, and T-105/T-118 for the full history). `engine/cli/` is now the sole implementation
of every one of those commands, so section 1 (the old byte-identity/dispatch checks) and
the former section 1b (T-048 handoff identity against a live `core/cli/atlas-handoff`) are
both gone — there is nothing left to drift against. Sections 2 and 3 below are the only
still-live regression coverage this file provides, and they do not depend on whether
`core/cli` exists anywhere, so this file no longer self-skips.

Nothing here touches ~/atlas or ~/atlas — it only reads them.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli"

G, R, D, X = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = R = D = X = ""
passed = failed = 0


def chk(desc, ok):
    global passed, failed
    if ok:
        print(f"  {G}PASS{X} {desc}"); passed += 1
    else:
        print(f"  {R}FAIL{X} {desc}"); failed += 1


def t(label):
    print(f"\n{D}— {label}{X}")


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --- 1. (retired by T-118) -------------------------------------------------------------
# atlas_paths.py/atlas_tickets.py/atlas_lifecycle.py/atlas-context/atlas-observe no longer
# have copies under ~/atlas/context/ or ~/atlas/core/cli/ to drift from each other — there
# is exactly one copy of each, in engine/cli/. Nothing left to check; see this file's own
# module docstring for the retirement record.

# --- 1b. (retired by T-118) -------------------------------------------------------------
# The T-048 handoff-identity check used to compare engine/cli/atlas-handoff against a live
# ~/atlas/core/cli/atlas-handoff dispatched copy. `core/cli/` no longer exists on this or
# any machine post-T-118 — there is exactly one atlas-handoff implementation, in
# engine/cli/. See test-mission-handoff.py for the still-live behavioral coverage of that
# command; this file only ever checked that a second copy stayed in sync, and there is no
# second copy left to sync.
t("T-118: no stale core/cli/atlas-handoff copy has reappeared")
engine_handoff = CLI / "atlas-handoff"
chk("engine/cli/atlas-handoff exists", engine_handoff.is_file())
chk("no ~/atlas/core/cli/atlas-handoff copy exists",
    not (Path.home() / "atlas" / "core" / "cli" / "atlas-handoff").exists())

# --- 2. Dispatch resolution: context/usage/lifecycle/observe now ignore ATLAS_HOME, -----
#         exactly like every other command (T-118) -------------------------------------
t("dispatch resolution: context/usage/lifecycle/observe ignore ATLAS_HOME, like tickets")


def run(cmd, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([str(CLI / "atlas"), *cmd], capture_output=True, text=True,
                          env=env, cwd=cwd or str(CLI))


with tempfile.TemporaryDirectory() as tmp:
    # A stub placed under a fake ATLAS_HOME/context/ must NEVER be picked up post-T118 —
    # if it is, some dispatch line regressed back to the retired ATLAS_HOME-relative
    # branch. Nothing under $SELF_DIR is stubbed: these commands only ever have one real
    # implementation now, so there is nothing to fake it against.
    fake_atlas = Path(tmp) / "fake-atlas"
    (fake_atlas / "context").mkdir(parents=True)
    for name in ("atlas-context", "atlas-usage", "atlas-lifecycle", "atlas-observe"):
        stub = fake_atlas / "context" / name
        stub.write_text(f'#!/bin/sh\necho "STUB:{name}: $@"\n')
        stub.chmod(0o755)

    for cmd in ("context", "usage", "lifecycle"):
        r = run([cmd], env_extra={"ATLAS_HOME": str(fake_atlas)})
        chk(f"'atlas {cmd}' ignores ATLAS_HOME and still runs engine/cli's own copy "
            f"(T-118 retired the context/ dispatch branch)",
            "STUB:" not in r.stdout and "STUB:" not in r.stderr)
    r = run(["observe", "--", "true"], env_extra={"ATLAS_HOME": str(fake_atlas)})
    chk("'atlas observe' ignores ATLAS_HOME for dispatch (still writes its observation "
        "store under the real ATLAS_HOME, which is a separate, correct behavior — this "
        "checks only which implementation ran)",
        "STUB:" not in r.stdout and "STUB:" not in r.stderr)

    r = run(["tickets", "list", "--project", "__no_such_project__"],
            env_extra={"ATLAS_HOME": str(fake_atlas)})
    chk("'atlas tickets' ignores ATLAS_HOME and still runs the repo's own copy "
        "(not yet cut over — must not accidentally start resolving into a fake atlas)",
        "STUB:" not in r.stdout and "STUB:" not in r.stderr)

# --- 3. No new, independent implementation location was introduced ---------------------
# Every `exec` line in the wrapper resolves to $SELF_DIR — the repo itself. T-118 removed
# the only other allowed root (${ATLAS_HOME:-...}/context/); a second root reappearing
# here would mean an independent implementation location was reintroduced.
t("the wrapper resolves to exactly one tree — no second implementation")
wrapper_text = (CLI / "atlas").read_text()
exec_lines = [l for l in wrapper_text.splitlines() if "exec \"" in l]
chk("at least one exec line found to check", len(exec_lines) > 0)
unexpected = [l.strip() for l in exec_lines if 'exec "$SELF_DIR/' not in l]
chk("every dispatch line targets $SELF_DIR, nothing else", not unexpected)
if unexpected:
    for l in unexpected:
        print(f"    unexpected dispatch: {l}")


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
