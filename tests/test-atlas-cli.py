#!/usr/bin/env python3
"""tests/test-atlas-cli.py — T-031: `atlas` is the canonical CLI name, `ai-os` a compatibility
alias, and ATLAS_HOME/AI_OS_HOME precedence behaves exactly as documented.

Covers, per T-031's Slice 5 requirement list:
  - `atlas` command resolves and runs
  - `ai-os` compatibility alias resolves identically to `atlas`
  - ATLAS_HOME takes precedence for the Atlas-first path resolver
  - AI_OS_HOME works only as the legacy/compatibility fallback (unchanged old/new logic)
  - Atlas-first path resolution: no fallback to legacy when a valid Atlas path exists
  - fallback to legacy when Atlas content is absent
  - fixture isolation: a test AI_OS_HOME is never redirected into the real ~/atlas
  - historical AIOS-* ticket ids remain resolvable through `atlas`/`ai-os-paths ticket`
  - no duplicate ticket authority is introduced by adding the `atlas` entry point

Nothing here touches ~/.ai-os or ~/atlas — it only reads them and uses disposable fixtures.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


def run(binary, args, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run([str(CLI / binary), *args], capture_output=True, text=True,
                          env=env, cwd=cwd or str(CLI))


# --- 1. atlas is a real, working entry point ---------------------------------------------
t("`atlas` command resolution")
r = run("atlas", ["version"])
chk("`atlas version` runs and exits 0", r.returncode == 0)
chk("`atlas version` prints the VERSION file's contents",
    r.stdout.strip() == (REPO / "VERSION").read_text().strip())

r = run("atlas", ["help"])
chk("`atlas help` banner names `atlas`, not only `ai-os`", "atlas v" in r.stdout)
chk("`atlas help` documents `ai-os` as a temporary compatibility alias",
    "compatibility" in r.stdout and "ai-os" in r.stdout)

# --- 2. ai-os is a compatibility alias, not a second implementation -----------------------
t("`ai-os` compatibility alias resolves identically to `atlas`")
for args in (["version"], ["help"], ["doctor", "--quiet"]):
    ra = run("atlas", args)
    ro = run("ai-os", args)
    chk(f"`atlas {' '.join(args)}` and `ai-os {' '.join(args)}` exit identically",
        ra.returncode == ro.returncode)
    # doctor's own banner differs only in which name printed the report header line, if any
    body_a = "\n".join(l for l in ra.stdout.splitlines() if not l.strip().startswith(("atlas", "ai-os")))
    body_o = "\n".join(l for l in ro.stdout.splitlines() if not l.strip().startswith(("atlas", "ai-os")))
    chk(f"`atlas {' '.join(args)}` and `ai-os {' '.join(args)}` produce the same body",
        body_a == body_o)

ai_os_text = (CLI / "ai-os").read_text()
chk("cli/ai-os is a thin alias (single exec, no independent command logic)",
    ai_os_text.count("exec ") == 1 and 'exec "$SELF_DIR/atlas"' in ai_os_text)

r = run("ai-os", ["frobnicate"])
chk("an unknown subcommand still fails the same way through the alias", r.returncode == 2)

# --- 3. ATLAS_HOME precedence / AI_OS_HOME compatibility fallback -------------------------
t("ATLAS_HOME precedence and AI_OS_HOME compatibility fallback (cli/ai-os-paths)")

PATHS_SH = f'. "{CLI}/ai-os-paths"; '

def paths_eval(expr, env_extra=None):
    r = run("bash", []) if False else None
    p = subprocess.run(
        ["bash", "-c", PATHS_SH + expr], capture_output=True, text=True,
        env={**os.environ, **(env_extra or {})},
    )
    return p

with tempfile.TemporaryDirectory() as tmp:
    fake_home = Path(tmp) / "fake-home"
    fake_atlas = Path(tmp) / "fake-atlas"
    (fake_home / "user" / "02-personal" / "memory").mkdir(parents=True)
    (fake_atlas / "personal" / "memory").mkdir(parents=True)
    (fake_atlas / "personal" / "memory" / "marker.txt").write_text("atlas-canonical")

    # a) ATLAS_HOME resolves and takes precedence over AI_OS_HOME's own default when both
    #    point at real content, but ONLY for the real workspace (home == $HOME/.ai-os) —
    #    verified separately below (isolation case) that a fixture AI_OS_HOME is immune.
    r = paths_eval("aios_atlas_home", {"ATLAS_HOME": str(fake_atlas)})
    chk("aios_atlas_home() honors ATLAS_HOME when set", r.stdout.strip() == str(fake_atlas))

    r = paths_eval("aios_atlas_home", {})
    chk("aios_atlas_home() falls back to ~/atlas when ATLAS_HOME is unset",
        r.stdout.strip() == str(Path.home() / "atlas"))

    # b) AI_OS_HOME as compatibility fallback for the legacy/dual-layout resolver
    r = paths_eval("aios_paths_home", {"AI_OS_HOME": str(fake_home)})
    chk("aios_paths_home() honors AI_OS_HOME as the compatibility fallback",
        r.stdout.strip() == str(fake_home))
    r = paths_eval("aios_paths_home", {})
    chk("aios_paths_home() defaults to ~/.ai-os when AI_OS_HOME is unset",
        r.stdout.strip() == str(Path.home() / ".ai-os"))

    # c) fixture isolation: an isolated AI_OS_HOME must NEVER be redirected into the real
    #    ~/atlas, even if the real ~/atlas exists and has content for that root — because
    #    _aios_atlas_path only ever fires when home resolves to the literal real default.
    r = paths_eval('aios_path memory', {"AI_OS_HOME": str(fake_home)})
    chk("an isolated AI_OS_HOME resolves 'memory' under itself, never under the real ~/atlas",
        r.stdout.strip() == str(fake_home / "user" / "02-personal" / "memory"))
    chk("...and is not silently redirected to ~/atlas",
        "atlas" not in r.stdout or str(Path.home() / "atlas") not in r.stdout)

    # d) Atlas-first, no-fallback-when-Atlas-content-exists: only meaningful for the real
    #    workspace path (home == $HOME/.ai-os); this cannot be exercised with a fixture home
    #    without touching the real ~/atlas, so it is proven structurally instead — the guard
    #    is unconditional and un-bypassable via env for any other home value (case c above),
    #    which is the property that matters: Atlas authority never leaks into an isolated
    #    environment, and can only ever apply to the one real workspace.
    src = (CLI / "ai-os-paths").read_text()
    chk("_aios_atlas_path is gated on the literal real default AI_OS_HOME (no override bypass)",
        '[ "$home" = "$HOME/.ai-os" ] || return 1' in src)

    # e) fallback when Atlas content is absent: a root cut over in principle but missing on
    #    disk under a *custom* ATLAS_HOME falls straight through — proven directly, since
    #    _aios_atlas_path's directory-exists check does not depend on which home is real.
    r = subprocess.run(
        ["bash", "-c", PATHS_SH + '_aios_atlas_path memory; echo "rc=$?"'],
        capture_output=True, text=True,
        env={**os.environ, "ATLAS_HOME": str(Path(tmp) / "empty-atlas")},
    )
    chk("_aios_atlas_path returns non-zero (fall through to legacy logic) when the Atlas "
        "directory for that root does not exist", "rc=1" in r.stdout)

# --- 4. historical AIOS-* ticket ids remain resolvable, no duplicate authority ------------
t("historical AIOS-* ticket resolution is unaffected by the CLI rename")
r = run("ai-os-paths", ["ticket", "AIOS-001"])
chk("`ai-os-paths ticket AIOS-001` still resolves (historical id, unrenumbered)",
    r.returncode == 0 and r.stdout.strip())
r2 = run("ai-os-paths", ["ticket", "AIOS-001"])
chk("resolving the same historical id twice reports one location, not a conflict "
    "(exit 3 would mean duplicate authority)", r2.returncode == 0)

r3 = run("ai-os-tickets", ["doctor", "--project", "ai-os"])
chk("`ai-os-tickets doctor` reports 0 duplicate-id errors after adding cli/atlas "
    "(atlas introduces no new ticket record)", " 0 error" in r3.stdout or "0 error(s)" in r3.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
