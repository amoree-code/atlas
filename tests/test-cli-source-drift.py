#!/usr/bin/env python3
"""tests/test-cli-source-drift.py — T-025: one canonical source per component, proven.

Two physical trees exist by design (`<repo>/cli/` and `~/atlas/`), a consequence of the
migration cutting commands over one at a time (T-016/017/018 moved `context`/`usage`/
`lifecycle`/`observe`; T-012 placed, but explicitly did not cut over, everything else).
That is a sanctioned transition state, not a bug — but it only stays safe as long as:

  1. every command's *dispatch* (which physical file actually runs) matches what the
     wrapper's own comments declare, including under a custom `ATLAS_HOME`;
  2. every file that is supposed to be a byte-identical mirror of its canonical source
     (T-012's "Phase D1 copy... byte-identical, untouched" invariant for `~/atlas/core/
     cli/`, and its "co-located" copy of `atlas_lifecycle.py` under `~/atlas/context/`)
     actually still is one, so a fix to the canonical file cannot silently stop applying
     to the copy a live, dispatched command reads.

(2) is exactly the failure this file exists to catch: T-024 edited the canonical
`atlas_tickets.py` and did not know a second, live-imported copy existed, breaking
`atlas context <archived-id>` until the drift was found and fixed by hand. This test makes
that class of failure a loud, fast, sub-second check instead of a manual discovery.

Nothing here touches ~/atlas or ~/atlas — it only reads them.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli"
ATLAS = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))

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


HAVE_ATLAS = (ATLAS / "core" / "cli").is_dir()

if not HAVE_ATLAS:
    print("  (skipped — no ~/atlas/core/cli found on this machine; nothing to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)

# --- 1. CORE_SHARED / CONTEXT_MECHANISM python libraries: declared byte-identical -------
# T-012 classified atlas_paths.py/atlas_tickets.py as CORE_SHARED ("stays core/cli/,
# unduplicated" — i.e. the atlas placement is supposed to be one file, not a drifting
# fork) and atlas_lifecycle.py as CONTEXT_MECHANISM ("copied to context/, co-located").
# Both classes carry the same real invariant this test checks: whatever the repo's copy
# says is what every dispatched command — repo-side or Atlas-side — actually reads.
t("CORE_SHARED python libraries stay byte-identical across every copy that must agree")
CORE_SHARED = ("atlas_paths.py", "atlas_tickets.py")
for name in CORE_SHARED:
    repo_f = CLI / name
    atlas_f = ATLAS / "core" / "cli" / name
    chk(f"{name}: repo copy exists", repo_f.is_file())
    chk(f"{name}: atlas/core/cli copy exists", atlas_f.is_file())
    if repo_f.is_file() and atlas_f.is_file():
        chk(f"{name}: repo and atlas/core/cli are byte-identical",
            sha(repo_f) == sha(atlas_f))

CONTEXT_MECHANISM = "atlas_lifecycle.py"
repo_f = CLI / CONTEXT_MECHANISM
core_f = ATLAS / "core" / "cli" / CONTEXT_MECHANISM
ctx_f = ATLAS / "context" / CONTEXT_MECHANISM
chk(f"{CONTEXT_MECHANISM}: all three copies exist (repo, core/cli, context)",
    repo_f.is_file() and core_f.is_file() and ctx_f.is_file())
if repo_f.is_file() and core_f.is_file() and ctx_f.is_file():
    h = sha(repo_f)
    chk(f"{CONTEXT_MECHANISM}: atlas/core/cli matches the canonical repo copy",
        sha(core_f) == h)
    chk(f"{CONTEXT_MECHANISM}: atlas/context (the dispatched command's own directory) "
        f"matches it too", sha(ctx_f) == h)

# --- 1b. T-048 handoff identity: core is intentionally not byte-identical to engine
# during the migration, but the live dispatched copy must carry the same approved
# identity behavior. This catches the exact failure where the engine copy was updated
# while `atlas handoff` still ran an older core copy.
t("T-048 handoff identity exists in both engine and the live core copy")
HANDOFF_IDENTITY_MARKERS = (
    "--source-client",
    "--source-session",
    "source_client",
    "source_session_id",
    "IDENTITY_UNSPECIFIED",
    "def identity_display",
)
engine_handoff = CLI / "atlas-handoff"
atlas_handoff = ATLAS / "core" / "cli" / "atlas-handoff"
chk("atlas-handoff engine copy exists", engine_handoff.is_file())
chk("atlas-handoff atlas/core/cli copy exists", atlas_handoff.is_file())
if engine_handoff.is_file() and atlas_handoff.is_file():
    engine_text = engine_handoff.read_text(errors="replace")
    atlas_text = atlas_handoff.read_text(errors="replace")
    for marker in HANDOFF_IDENTITY_MARKERS:
        chk(f"atlas-handoff identity marker {marker!r} is present in both copies",
            marker in engine_text and marker in atlas_text)

# --- 2. Dispatch tracing: the wrapper sends each representative command to the copy it --
#         claims to, including honoring a custom ATLAS_HOME -----------------------------
t("dispatch resolution: representative commands run from their declared canonical copy")


def run(cmd, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([str(CLI / "atlas"), *cmd], capture_output=True, text=True,
                          env=env, cwd=cwd or str(CLI))


with tempfile.TemporaryDirectory() as tmp:
    fake_atlas = Path(tmp) / "fake-atlas"
    (fake_atlas / "context").mkdir(parents=True)
    for name in ("atlas-context", "atlas-usage", "atlas-lifecycle", "atlas-observe"):
        stub = fake_atlas / "context" / name
        stub.write_text(f'#!/bin/sh\necho "STUB:{name}: $@"\n')
        stub.chmod(0o755)

    for cmd, marker in (("context", "atlas-context"), ("usage", "atlas-usage"),
                        ("lifecycle", "atlas-lifecycle"), ("observe", "atlas-observe")):
        r = run([cmd] if cmd != "observe" else ["observe", "--", "true"],
                env_extra={"ATLAS_HOME": str(fake_atlas)})
        chk(f"'atlas {cmd}' honors a custom ATLAS_HOME (was the T-025 bug for 'observe')",
            f"STUB:{marker}" in r.stdout)

    r = run(["tickets", "list", "--project", "__no_such_project__"],
            env_extra={"ATLAS_HOME": str(fake_atlas)})
    chk("'atlas tickets' ignores ATLAS_HOME and still runs the repo's own copy "
        "(not yet cut over — must not accidentally start resolving into a fake atlas)",
        "STUB:" not in r.stdout and "STUB:" not in r.stderr)

# --- 3. No new, independent third implementation was introduced -------------------------
# Every `exec` line in the wrapper resolves to exactly one of two roots: the repo itself
# ($SELF_DIR) or the Atlas context tree (${ATLAS_HOME:-...}/context/). A third root
# appearing here would mean a new independent implementation location was introduced.
t("the wrapper still resolves to exactly the two known trees — no third implementation")
wrapper_text = (CLI / "atlas").read_text()
exec_lines = [l for l in wrapper_text.splitlines() if "exec \"" in l]
chk("at least one exec line found to check", len(exec_lines) > 0)
allowed = ('exec "$SELF_DIR/', 'exec "${ATLAS_HOME:-$HOME/atlas}/context/')
unexpected = [l.strip() for l in exec_lines if not any(a in l for a in allowed)]
chk("every dispatch line targets $SELF_DIR or ${ATLAS_HOME:-...}/context/, nothing else",
    not unexpected)
if unexpected:
    for l in unexpected:
        print(f"    unexpected dispatch: {l}")


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
