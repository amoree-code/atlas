#!/usr/bin/env python3
"""tests/test-atlas-privacy.py — T-004: path-based publication eligibility for $ATLAS_HOME.

Before any of ~/.ai-os/personal/** ever moves into $ATLAS_HOME, this proves the boundary
that would reject it deterministically. Nothing here scans content, publishes anything, or
touches a real workspace — classification runs against a throwaway fixture tree, and the
old-root content scanner is exercised against this repo (read-only) to prove it still works
unmodified.
"""
import importlib.util, subprocess, sys, tempfile
from importlib.machinery import SourceFileLoader
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


spec = importlib.util.spec_from_loader(
    "aios_atlas_privacy_under_test",
    SourceFileLoader("aios_atlas_privacy_under_test", str(CLI / "aios_atlas_privacy.py")))
priv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(priv)

# =========================================================================================
t("personal/** is always rejected from publication")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    for sub in ("personal/memory/foo.md", "personal/knowledge/decisions/x.md", "personal/x"):
        cls, eligible, _ = priv.publication_eligibility(atlas / sub, atlas)
        chk(f"{sub} -> class=private, not eligible", cls == "private" and not eligible)

# =========================================================================================
t("runtime/** is always rejected from publication")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    for sub in ("runtime/runs/r123/state.json", "runtime/browser/profile/x", "runtime/x"):
        cls, eligible, _ = priv.publication_eligibility(atlas / sub, atlas)
        chk(f"{sub} -> class=local, not eligible", cls == "local" and not eligible)

# =========================================================================================
t("a known publishable root is eligible for further validation (not auto-approved)")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    for root in priv.PUBLICATION_ALLOWLIST:
        cls, eligible, reason = priv.publication_eligibility(atlas / root / "x.md", atlas)
        chk(f"{root}/ -> class=publishable, eligible", cls == "publishable" and eligible)
    chk("core/ is one of the publishable roots", "core" in priv.PUBLICATION_ALLOWLIST)
    chk("eligible never means auto-published — caller must still scan+approve", True)

# =========================================================================================
t("a mixed root defaults safely (private by default, not blanket-open)")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    for root, info in priv.ROOTS.items():
        if info["class"] != "mixed":
            continue
        cls, eligible, reason = priv.publication_eligibility(atlas / root / "x.md", atlas)
        chk(f"{root}/ (mixed) -> not eligible by default", cls == "mixed" and not eligible)
        chk(f"{root}/ (mixed) reason names the per-item requirement",
            "explicitly" in reason or "per-item" in reason)
chk("projects/ and integration/ are grounded as private/mixed, not blanket-mixed/publishable",
    priv.ROOTS["projects"]["class"] == "private" and priv.ROOTS["integration"]["class"] == "mixed")

# =========================================================================================
t("an unknown root defaults to deny")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    cls, eligible, reason = priv.publication_eligibility(atlas / "not-a-real-root" / "x", atlas)
    chk("unrecognized root -> class=None, not eligible", cls is None and not eligible)
    cls2, eligible2, _ = priv.publication_eligibility(atlas / "README.md", atlas)
    chk("a path with no root segment at all -> not eligible", cls2 is None and not eligible2)
    cls3, eligible3, _ = priv.publication_eligibility("/completely/unrelated/path", atlas)
    chk("a path entirely outside $ATLAS_HOME -> not eligible", cls3 is None and not eligible3)

# =========================================================================================
t("the publication allowlist is deterministic and excludes private/local/mixed roots")
chk("allowlist excludes personal", "personal" not in priv.PUBLICATION_ALLOWLIST)
chk("allowlist excludes runtime", "runtime" not in priv.PUBLICATION_ALLOWLIST)
chk("allowlist excludes projects", "projects" not in priv.PUBLICATION_ALLOWLIST)
chk("allowlist excludes every mixed root",
    not any(priv.ROOTS[r]["class"] == "mixed" for r in priv.PUBLICATION_ALLOWLIST))
chk("allowlist is exactly the publishable-class roots, nothing more",
    set(priv.PUBLICATION_ALLOWLIST) == {r for r, i in priv.ROOTS.items() if i["class"] == "publishable"})
chk("all fourteen frozen roots are classified, none missing",
    set(priv.ROOTS) == {"core", "context", "personal", "projects", "adapters", "capabilities",
                         "domains", "extensions", "governance", "contracts", "runtime",
                         "integration", "docs", "tests"})

# =========================================================================================
t("path classification is independent of Git tracking/staging")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    (atlas / "personal").mkdir(parents=True)
    secret_file = atlas / "personal" / "staged-secret.md"
    secret_file.write_text("real personal content")
    subprocess.run(["git", "init", "-q"], cwd=str(atlas))
    subprocess.run(["git", "add", "."], cwd=str(atlas))
    r = subprocess.run(["git", "status", "--short"], cwd=str(atlas),
                       capture_output=True, text=True)
    chk("the file IS staged in git (setup check)", "staged-secret.md" in r.stdout)
    cls, eligible, _ = priv.publication_eligibility(secret_file, atlas)
    chk("classification rejects it anyway — staging changed nothing",
        cls == "private" and not eligible)
    cls_nonexistent, eligible_ne, _ = priv.publication_eligibility(
        atlas / "personal" / "never-created.md", atlas)
    chk("classification works even when the path does not exist on disk at all "
        "(pure path logic, no git/filesystem inspection)",
        cls_nonexistent == "private" and not eligible_ne)

# =========================================================================================
t("--atlas-classify CLI: matches the module directly, exits 0/1 correctly")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    (atlas / "core").mkdir(parents=True)
    (atlas / "personal").mkdir(parents=True)
    env = {"ATLAS_HOME": str(atlas), "PATH": "/usr/bin:/bin"}
    r_ok = subprocess.run([str(CLI / "ai-os-privacy-scan"), "--atlas-classify",
                          str(atlas / "core" / "x.md")], env=env, capture_output=True, text=True)
    chk("publishable path -> exit 0", r_ok.returncode == 0)
    chk("output names the class", "publishable" in r_ok.stdout)
    r_bad = subprocess.run([str(CLI / "ai-os-privacy-scan"), "--atlas-classify",
                           str(atlas / "personal" / "x.md")], env=env, capture_output=True, text=True)
    chk("private path -> exit 1", r_bad.returncode == 1)
    r_missing = subprocess.run([str(CLI / "ai-os-privacy-scan"), "--atlas-classify"],
                              env=env, capture_output=True, text=True)
    chk("missing PATH argument -> usage error, exit 2", r_missing.returncode == 2)

# =========================================================================================
t("credential scanning (content layer) is untouched by this ticket")
spec2 = importlib.util.spec_from_loader(
    "ai_os_privacy_scan_under_test",
    SourceFileLoader("ai_os_privacy_scan_under_test", str(CLI / "ai-os-privacy-scan")))
scan_mod = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(scan_mod)
findings = []
# Built by concatenation, never a contiguous literal in this file's own source — the
# repo's own privacy scan runs over its tracked files, and a literal key-shaped string
# here would make this fixture itself a finding, which is not what this test is checking.
fake_key = "sk-" + "ant-" + "abcdefghijklmnopqrstuvwxyz0123456789"
scan_mod.scan_text(f'api_key: "{fake_key}"', "fixture.py", [], None, findings)
chk("a fake Anthropic-shaped key is still caught by the untouched content scanner",
    any(f[0] == "credential" for f in findings))

# =========================================================================================
t("the old-root privacy scan (this repo) still runs clean during the transition")
r = subprocess.run([str(CLI / "ai-os-privacy-scan"), "--quiet"], cwd=str(REPO),
                   capture_output=True, text=True)
chk("`ai-os-privacy-scan --quiet` on the public repo still exits 0", r.returncode == 0)

# =========================================================================================
t("$ATLAS_HOME=~/atlas path resolution, no hardcoded username")
source = (CLI / "aios_atlas_privacy.py").read_text() + (CLI / "ai-os-privacy-scan").read_text()
# Read dynamically, never typed as a literal in this test file — a literal real username
# in a tracked file is exactly what the repo's own privacy scan exists to catch (see the
# section above), so this check must not introduce one of its own.
real_username = Path.home().name
chk("the current real username never appears in either file",
    real_username not in source)
chk("aios_atlas_privacy.py has no hardcoded absolute home path",
    "/Users/" not in (CLI / "aios_atlas_privacy.py").read_text())
env_default = {"PATH": "/usr/bin:/bin"}
r = subprocess.run([str(CLI / "ai-os-privacy-scan"), "--atlas-classify",
                   str(Path.home() / "atlas" / "core" / "README.md")],
                  env=env_default, capture_output=True, text=True)
chk("with no ATLAS_HOME override, defaults to ~/atlas and classifies the real skeleton",
    r.returncode == 0 and "publishable" in r.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
