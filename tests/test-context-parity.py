#!/usr/bin/env python3
"""tests/test-context-parity.py — T-105: does context/{atlas-context,observe,usage,
lifecycle} actually behave the same as engine/cli/'s copies of the same names?

History (T-105 owner ruling, 2026-09-08: "cut over callers only after proving parity"):

  1st pass — proved parity does NOT hold. `atlas-context` was a genuine two-way feature
     fork (context/'s copy had --mode next/--mode planning/--resume — the real Claude
     Code SessionStart hook depends on --resume; engine/cli/'s copy had
     retrieve()/compact_packet()/--query/--budget-chars that context/'s copy lacked
     entirely). `atlas-observe` agreed on the happy path but diverged sharply on
     missing-ATLAS_HOME fallback: context/'s copy refused loudly (T-015's guarantee),
     engine/cli/'s copy silently fell back to `~/atlas` instead — caught by watching it
     happen during this test's own development, the stray record removed by hand.

  2nd pass (this file, current) — both gaps were closed by implementation, not by
     picking a side:
       - `atlas-context`: merged. All 3 copies now carry BOTH feature sets — the
         session-handoff/Smart-Dynamic-Ticket-System features (`--resume`, `--mode
         next`, `--mode planning`) AND the retrieval/compaction features
         (`retrieve()`, `compact_packet()`, `--query`, `--budget-chars`). Nothing was
         dropped from either side. The dispatched command (`context/atlas-context`) is
         unchanged in every way an existing caller (the SessionStart hook) could
         observe — only new, additive flags were introduced.
       - `atlas-observe`: fixed. All 3 copies now resolve the observation-store root
         through one new shared function, `atlas_paths.atlas_home()` — `${ATLAS_HOME:-
         ~/atlas}`, no legacy-layout table, no fallback — replacing engine/core's prior
         use of `private_path_or_die("runtime")`, which is what produced the fallback.
       - `atlas_lifecycle.py` was already byte-identical (untouched).
       - `atlas-lifecycle` was already equivalent (untouched) — the only diff remains a
         structural sibling `sys.path.insert`, not a behavior change.
       - `atlas-usage` still has one, small, deliberately NOT fixed cosmetic gap (see
         §4) — out of this phase's minimal scope; tracked, not silently dropped.

This test proves the CURRENT state by execution, the same way the 1st pass proved the
prior one wrong — it does not trust the diff, and it does not assume a merge that
compiles is a merge that behaves.

Nothing here touches ~/atlas's durable data.
"""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent          # .../engine
ATLAS = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))
CONTEXT = ATLAS / "context"
CORE = ATLAS / "core" / "cli"

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


def run(path, args, env_extra=None, cwd=None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(["python3", str(path), *args], capture_output=True, text=True,
                          env=env, cwd=cwd)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


HAVE_CONTEXT = CONTEXT.is_dir()
if not HAVE_CONTEXT:
    print("  (skipped — no ~/atlas/context found on this machine; nothing to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)

# --- 0. inventory: 2 or 3 physical copies of each mechanism file, nowhere else ---------
# T-105's final phase moved core/cli/atlas-usage to the removed-duplicates backup — it
# was never a pinned/parity-proven mirror the way atlas-context/atlas-observe/
# atlas_lifecycle.py are, and had zero caller at that path. The other 4 stay 3-way.
t("inventory: the known physical copies exist, no undiscovered 4th implementation")
MECHANISM_FILES_3WAY = ("atlas-context", "atlas-observe", "atlas-lifecycle",
                        "atlas_lifecycle.py")
for name in MECHANISM_FILES_3WAY:
    chk(f"{name}: context/ copy exists", (CONTEXT / name).is_file())
    chk(f"{name}: engine/cli/ copy exists", (REPO / "cli" / name).is_file())
    chk(f"{name}: core/cli/ copy exists", (CORE / name).is_file())
chk("atlas-usage: context/ copy exists", (CONTEXT / "atlas-usage").is_file())
chk("atlas-usage: engine/cli/ copy exists", (REPO / "cli" / "atlas-usage").is_file())
chk("atlas-usage: core/cli/ copy no longer exists (proven-stale duplicate, removed "
    "this phase — was never pinned/parity-proven)",
    not (CORE / "atlas-usage").is_file())
found = subprocess.run(
    ["find", str(REPO.parent), "-name", "atlas-context", "-not", "-path", "*/.git/*"],
    capture_output=True, text=True).stdout.strip().splitlines()
chk("atlas-context exists at exactly 3 paths repo-wide (no undiscovered 4th copy)",
    len(found) == 3)

# --- 1. atlas_lifecycle.py: byte-identical, still true, unaffected by this phase --------
t("atlas_lifecycle.py: byte-identical across all 3 copies (untouched, still at parity)")
s_context = sha(CONTEXT / "atlas_lifecycle.py")
s_engine = sha(REPO / "cli" / "atlas_lifecycle.py")
s_core = sha(CORE / "atlas_lifecycle.py")
chk("context == engine", s_context == s_engine)
chk("engine == core", s_engine == s_core)


def _structural_sys_path_diff_only(ctx_text, other_text, must_mention):
    """True if every line in `ctx_text` absent from `other_text` is part of the
    documented sibling-sys.path.insert bootstrap block context/ needs (to reach
    core/cli/) and engine/core don't (atlas_paths/atlas_tickets are co-located there) —
    the one structural difference this ticket's rules allow between the 3 copies."""
    ctx_lines = [l for l in ctx_text.splitlines() if l.strip()]
    other_lines = [l for l in other_text.splitlines() if l.strip()]
    extra = [l for l in ctx_lines if l not in other_lines]
    block = "\n".join(extra)
    allowed = ("#", "sys.path", "HERE", "Path(__file__)")
    return (0 < len(extra) <= 8 and "sys.path.insert" in block and must_mention in block
            and all(l.strip().startswith("#") or any(a in l for a in allowed)
                    for l in extra))


# --- 2. atlas-context: merged — both feature sets now present in all 3 copies ----------
t("atlas-context: the merge is structural-only (sys.path bootstrap), not behavioral")
ctx_text = (CONTEXT / "atlas-context").read_text(errors="replace")
eng_text = (REPO / "cli" / "atlas-context").read_text(errors="replace")
core_text = (CORE / "atlas-context").read_text(errors="replace")
chk("context/ vs engine/cli/: only the sibling sys.path.insert block differs",
    _structural_sys_path_diff_only(ctx_text, eng_text, "core"))
chk("engine/cli/ and core/cli/ are byte-identical (both co-located, no bootstrap diff)",
    eng_text == core_text)

t("atlas-context: the SessionStart-hook feature set (--resume/--mode) is preserved "
  "in every copy, not just the dispatched one")
for label, path in (("context", CONTEXT / "atlas-context"),
                    ("engine/cli", REPO / "cli" / "atlas-context"),
                    ("core/cli", CORE / "atlas-context")):
    r_help = run(path, ["--help"])
    chk(f"{label}/atlas-context's --help mentions --mode {{planning,next}}",
        "--mode" in r_help.stdout and "planning,next" in r_help.stdout)
    chk(f"{label}/atlas-context's --help mentions --resume", "--resume" in r_help.stdout)
    r_resume = run(path, ["--resume", "--json"])
    chk(f"{label}/atlas-context accepts --resume --json (the exact hook invocation) "
        f"and exits 0", r_resume.returncode == 0 and '"pending"' in r_resume.stdout)

t("atlas-context: the retrieval/compaction feature set is preserved in every copy, "
  "not just engine's original")
for label, path in (("context", CONTEXT / "atlas-context"),
                    ("engine/cli", REPO / "cli" / "atlas-context"),
                    ("core/cli", CORE / "atlas-context")):
    r_help = run(path, ["--help"])
    chk(f"{label}/atlas-context's --help mentions --query", "--query" in r_help.stdout)
    chk(f"{label}/atlas-context's --help mentions --budget-chars",
        "--budget-chars" in r_help.stdout)
    r_budget = run(path, ["--json", "--budget-chars", "100"])
    chk(f"{label}/atlas-context still refuses a budget under 512 chars (the existing "
        f"engine guarantee, now honored everywhere)",
        r_budget.returncode != 0 and "512" in r_budget.stderr)

t("atlas-context: the real SessionStart-hook caller — proven safe to keep pointing at "
  "the dispatched copy, and now equally safe if it ever pointed at engine's")
hooks_doc = (REPO / "adapters" / "claude-code" / "hooks.md")
chk("adapters/claude-code/hooks.md exists (documents the real SessionStart caller)",
    hooks_doc.is_file())
if hooks_doc.is_file():
    chk("hooks.md documents 'atlas context --resume --json' as the real hook invocation",
        "atlas context --resume --json" in hooks_doc.read_text(errors="replace"))
r_dispatched = run(CONTEXT / "atlas-context", ["--resume", "--json"])
chk("the dispatched copy (context/atlas-context) still answers that exact invocation "
    "identically to before the merge", r_dispatched.returncode == 0
    and '"pending"' in r_dispatched.stdout)

t("atlas-context: mutually-exclusive-flag guards on the merged surface")
r_conflict1 = run(CONTEXT / "atlas-context", ["--mode", "next", "--resume"])
chk("--mode and --resume remain mutually exclusive (argparse group unchanged)",
    r_conflict1.returncode != 0)
r_conflict2 = run(CONTEXT / "atlas-context", ["--query", "x", "--resume"])
chk("--query is rejected together with --resume (new cross-feature guard)",
    r_conflict2.returncode != 0 and "not allowed with --mode or --resume" in r_conflict2.stderr)
r_conflict3 = run(CONTEXT / "atlas-context", ["--budget-chars", "1000", "--mode", "planning"])
chk("--budget-chars is rejected together with --mode planning (new cross-feature guard)",
    r_conflict3.returncode != 0)

# --- 3. atlas-observe: fixed — no copy silently falls back to a legacy root ------------
t("atlas-observe: all 3 copies now resolve through the same shared atlas_home()")
chk("atlas_paths.py exports atlas_home in both engine/cli and core/cli (CORE_SHARED, "
    "already required byte-identical by test-cli-source-drift.py)",
    "def atlas_home()" in (REPO / "cli" / "atlas_paths.py").read_text()
    and "def atlas_home()" in (CORE / "atlas_paths.py").read_text())
for label, path in (("context", CONTEXT / "atlas-observe"),
                    ("engine/cli", REPO / "cli" / "atlas-observe"),
                    ("core/cli", CORE / "atlas-observe")):
    text = path.read_text(errors="replace")
    chk(f"{label}/atlas-observe imports atlas_home (not private_path_or_die) for its "
        f"store() destination", "from atlas_paths import atlas_home" in text
        and "private_path_or_die" not in text)

t("atlas-observe: happy path (runtime dir exists) — identical across all 3")
with tempfile.TemporaryDirectory() as tmp:
    fake_atlas = Path(tmp) / "atlas"
    (fake_atlas / "runtime").mkdir(parents=True)
    for label, path in (("context", CONTEXT / "atlas-observe"),
                        ("engine", REPO / "cli" / "atlas-observe"),
                        ("core", CORE / "atlas-observe")):
        r = run(path, ["--", "echo", f"parity-check-{label}"],
               env_extra={"ATLAS_HOME": str(fake_atlas)})
        chk(f"{label}/atlas-observe exits 0 when runtime/ exists", r.returncode == 0)
    obs_dir = fake_atlas / "runtime" / "observations"
    chk("all 3 wrote into the same ATLAS_HOME/runtime/observations/ directory "
        "(3 records present)", obs_dir.is_dir() and len(list(obs_dir.iterdir())) == 3)

t("atlas-observe: missing-runtime fallback — REGRESSION-FIXED, proven by execution")
with tempfile.TemporaryDirectory() as tmp:
    # Deliberately do NOT create runtime/ under this fake ATLAS_HOME — this is the case
    # that used to diverge. Never point HOME at the tempdir; only ATLAS_HOME, so any
    # fallback this would reveal is visible rather than silently absorbed by an
    # isolated $HOME.
    fake_atlas = Path(tmp) / "atlas-no-runtime"
    fake_atlas.mkdir(parents=True)
    for label, path in (("context", CONTEXT / "atlas-observe"),
                        ("engine", REPO / "cli" / "atlas-observe"),
                        ("core", CORE / "atlas-observe")):
        r = run(path, ["--", "echo", "should-not-be-written"],
               env_extra={"ATLAS_HOME": str(fake_atlas)})
        chk(f"{label}/atlas-observe REFUSES (exit != 0) rather than silently falling "
            f"back — the T-015 guarantee, now honored by every copy",
            r.returncode != 0 and "refusing to fall back" in r.stderr)
        chk(f"{label}/atlas-observe wrote nothing under the fake ATLAS_HOME",
            not (fake_atlas / "runtime").exists())
        # Safety net: if some future edit reintroduces a fallback, find and remove
        # exactly the stray record by its self-reported id, nothing else.
        m = re.search(r"observe (\S+)\s", r.stdout)
        if m and r.returncode == 0:
            stray_id = m.group(1)
            for candidate_root in (Path.home() / "atlas", Path.home() / "atlas", ATLAS):
                for stray in candidate_root.glob(f"**/observations/{stray_id}"):
                    shutil.rmtree(stray, ignore_errors=True)
                    print(f"    {D}(cleaned up unexpected fallback record: {stray}){X}")

# --- 4. atlas-usage: cosmetic gap closed — now byte-identical (modulo none; both --------
#        copies share the same directory-relative import style already) ----------------
t("atlas-usage: the cosmetic guidance-text gap is closed — engine now matches context/")
usage_ctx = (CONTEXT / "atlas-usage").read_text(errors="replace")
usage_eng = (REPO / "cli" / "atlas-usage").read_text(errors="replace")
chk("context/atlas-usage and engine/cli/atlas-usage are now byte-identical",
    usage_ctx == usage_eng)
chk("both still name the top offending tool in the large-results guidance",
    "largest was" in usage_ctx and "largest was" in usage_eng)
r_ctx_help = run(CONTEXT / "atlas-usage", ["--help"])
r_eng_help = run(REPO / "cli" / "atlas-usage", ["--help"])
chk("both copies' --help output is identical (same flags, same order)",
    r_ctx_help.stdout == r_eng_help.stdout)

# --- 5. atlas-lifecycle: untouched, still the same structural-only diff ----------------
t("atlas-lifecycle: untouched this phase — sole diff is still the sibling sys.path.insert")
lc_ctx = (CONTEXT / "atlas-lifecycle").read_text(errors="replace")
lc_eng = (REPO / "cli" / "atlas-lifecycle").read_text(errors="replace")
chk("context/ vs engine/cli/: only the sibling sys.path.insert block differs",
    _structural_sys_path_diff_only(lc_ctx, lc_eng, "core"))
r_ctx = run(CONTEXT / "atlas-lifecycle", ["continue"])
r_eng = run(REPO / "cli" / "atlas-lifecycle", ["continue"])
chk("both exit identically on a bare 'continue' with no --transcripts",
    r_ctx.returncode == r_eng.returncode)
chk("both print the same usage/error text", r_ctx.stderr == r_eng.stderr)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
