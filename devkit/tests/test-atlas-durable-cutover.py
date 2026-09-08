#!/usr/bin/env python3
"""tests/test-atlas-durable-cutover.py — T-030/T-046: Atlas-first resolution in cli/atlas-paths.

Proves the durable-data authority cutover (personal/, projects/, governance's rules+
policies, plus T-046's reopened runtime/config/skills/agents/helpers/schemas/sessions)
added to `cli/atlas-paths`: Atlas is preferred for the real workspace when its directory
exists, legacy is the automatic fallback otherwise, and — the property every existing
`tests/test-contract.sh` fixture depends on — an isolated/alternate `ATLAS_HOME` never
picks up the real `~/atlas`, so this change is invisible to every prior test.

Nothing here touches the real `~/atlas` or `~/atlas` destructively; fixtures use throwaway
temp directories for ATLAS_HOME (mirroring test-contract.sh's own pattern) and, for the one
real-workspace check, only reads.
"""
import os, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PA = REPO / "cli" / "atlas-paths"

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


def run(args, env):
    full_env = {**os.environ, **env}
    return subprocess.run([str(PA)] + args, capture_output=True, text=True, env=full_env)


# =========================================================================================
t("an isolated ATLAS_HOME never resolves through Atlas, even when it exists on this machine")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-workspace"
    (fixture / "personal" / "memory").mkdir(parents=True)
    (fixture / "personal" / "memory" / "MEMORY.md").write_text("fixture memory")
    env = {"ATLAS_HOME": str(fixture)}
    r = run(["get", "memory"], env)
    chk("resolves inside the fixture, not ~/atlas", r.stdout.strip() == str(fixture / "personal" / "memory"))
    chk("exit 0", r.returncode == 0)

with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-workspace-2"
    fixture.mkdir(parents=True)
    env = {"ATLAS_HOME": str(fixture), "ATLAS_HOME": str(Path.home() / "atlas")}
    r = run(["get", "memory"], env)
    chk("even with ATLAS_HOME explicitly pointed at the real, populated ~/atlas, an "
        "isolated ATLAS_HOME still resolves its own (legacy old/new) logic, not Atlas",
        str(Path.home() / "atlas") not in r.stdout)

# =========================================================================================
t("the real workspace (no ATLAS_HOME override) resolves the cut-over roots through Atlas "
  "when ~/atlas holds the directory")
real_atlas = Path.home() / "atlas"
if (real_atlas / "personal" / "memory").is_dir():
    env = {}
    for root, rel in (("memory", "personal/memory"), ("knowledge", "personal/knowledge"),
                       ("projects", "projects"), ("rules", "governance/rules"),
                       ("policies", "governance/policies")):
        r = run(["get", root], env)
        chk(f"{root} -> resolves under the real ~/atlas/{rel}",
            r.stdout.strip() == str(real_atlas / rel))
else:
    chk("~/atlas/personal/memory not present on this machine — skipped (not a failure)", True)

# =========================================================================================
t("T-046 (owner reopened T-030/T-045's permanent-legacy ruling): runtime/config/skills/"
  "agents/helpers/schemas/sessions are now cut over to Atlas too, once physically migrated")
if real_atlas.is_dir():
    env = {}
    for root in ("skills", "agents", "config", "helpers", "schemas", "sessions", "runtime"):
        r = run(["get", root], env)
        chk(f"{root} -> resolves under the real ~/atlas/{root} (T-046 cutover)",
            r.stdout.strip() == str(real_atlas / root))
else:
    chk("~/atlas not present on this machine — skipped (not a failure)", True)

# =========================================================================================
t("legacy fallback is automatic when Atlas lacks the directory (reversibility)")
# The Atlas-first guard is keyed on ATLAS_HOME resolving to the literal real default
# ($HOME/atlas); this environment already exports a real ATLAS_HOME (confirmed: it
# always equals $HOME/atlas here), so leaving both ATLAS_HOME and HOME untouched and
# only redirecting ATLAS_HOME to an empty fixture exercises the real guard-passes-but-
# Atlas-directory-missing path against the real legacy workspace, without touching it.
real_atlas_home = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))
if real_atlas_home == Path.home() / "atlas" and (real_atlas_home / "personal" / "memory").is_dir():
    with tempfile.TemporaryDirectory() as tmp:
        fake_atlas = Path(tmp) / "atlas-empty"
        fake_atlas.mkdir(parents=True)
        env = {"ATLAS_HOME": str(fake_atlas)}
        r = run(["get", "memory"], env)
        chk("Atlas dir exists but lacks personal/memory -> falls through to the real "
            "legacy workspace, not an error",
            r.stdout.strip() == str(real_atlas_home / "personal" / "memory") and r.returncode == 0)
else:
    chk("ATLAS_HOME is not the real default workspace on this run — skipped (not a failure)", True)

# =========================================================================================
t("atlas_ticket: the real workspace resolves a known ticket ID through Atlas, no duplicate-"
  "authority conflict from the flat/archived placement split")
if (real_atlas / "projects").is_dir():
    for tid in ("AIOS-020", "T-029", "AIOS-001", "T-006"):
        r = run(["ticket", tid], {})
        chk(f"ticket {tid} resolves cleanly under ~/atlas (no CONFLICT)",
            r.returncode == 0 and str(real_atlas) in r.stdout)
else:
    chk("~/atlas/projects not present on this machine — skipped (not a failure)", True)

# =========================================================================================
t("atlas_ticket: an isolated ATLAS_HOME's ticket resolution is unaffected by Atlas")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-tickets"
    (fixture / "projects" / "demo" / "tickets" / "DEMO-001").mkdir(parents=True)
    (fixture / "projects" / "demo" / "tickets" / "DEMO-001" / "task.md").write_text(
        "---\nid: DEMO-001\nstate: active\n---\n")
    env = {"ATLAS_HOME": str(fixture)}
    r = run(["ticket", "DEMO-001"], env)
    chk("resolves inside the fixture project tree", r.stdout.strip() ==
        str(fixture / "projects" / "demo" / "tickets" / "DEMO-001"))

# =========================================================================================
# T-045 Phase 1 — the `atlas tickets` CLI contract (not just `atlas-paths` in isolation):
# every ticket subcommand shares one resolved root per invocation, ATLAS_HOME is the
# canonical ticket authority for the real workspace, ATLAS_HOME cannot override an existing
# canonical root, a malformed canonical root fails loud, and no invocation ever combines
# records from both roots. Every fixture below is a throwaway temp dir; nothing here writes
# to the real ~/atlas or ~/atlas, and ATLAS_HOME is left at its real default throughout (the
# Atlas-first guard only ever engages for the one real workspace, by design — see
# `_atlas_atlas_path` in cli/atlas-paths).
CLI = REPO / "cli"


def run_cli(args, atlas_home=None, extra_env=None):
    env = dict(os.environ)
    if atlas_home is not None:
        env["ATLAS_HOME"] = str(atlas_home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([str(CLI / "atlas"), "tickets", *args],
                          capture_output=True, text=True, env=env)


def make_fixture_project(base, project="demo-proj", ticket_id="T-900"):
    proj = base / "projects" / project
    (proj / "tickets" / ticket_id).mkdir(parents=True)
    (proj / "tickets" / ticket_id / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\n"
        f"id: {ticket_id}\ntitle: fixture ticket\nstate: active\nproject: {project}\n\n"
        "opened_at: 2026-01-01 12:00 PM\nupdated_at: 2026-01-01 12:00 PM\n\n"
        "references: []\nartifacts: []\nrequirement: REQ-FIX\n"
        "goal: fixture only\npriority: level_3\ndecision_required: false\n"
        "blocked_by: none\n\n"
        'checklist:\n  - "[ ] fixture step"\n\n'
        "checkpoint:\n  current: fixture\n  updated_at: 2026-01-01 12:00 PM\n---\n\n"
        "## Objective\n\nfixture\n\n## Next action\n\nfixture\n")
    return proj


REAL_ATLAS_HOME_IS_DEFAULT = (Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))
                              == Path.home() / "atlas")

t("`atlas tickets`: default environment (no ATLAS_HOME override) resolves the real "
  "canonical root when it holds ticket data")
if REAL_ATLAS_HOME_IS_DEFAULT and (real_atlas / "projects").is_dir():
    r = run_cli(["show", "T-045"])
    chk("T-045 (written this session under ~/atlas) is visible with no ATLAS_HOME override",
        r.returncode == 0 and "T-045" in r.stdout)
else:
    chk("real ~/atlas/projects not present on this machine — skipped (not a failure)", True)

t("`atlas tickets`: an explicit ATLAS_HOME fixture becomes the sole resolved root")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-atlas"
    make_fixture_project(fixture, ticket_id="T-901")
    r = run_cli(["list", "--project", "demo-proj"], atlas_home=fixture)
    chk("lists the fixture ticket", r.returncode == 0 and "T-901" in r.stdout)
    chk("never shows a real-workspace id (no cross-root leakage)",
        "T-045" not in r.stdout and "T-040" not in r.stdout)

t("`atlas tickets`: ATLAS_HOME cannot override an existing canonical ATLAS_HOME root")
if REAL_ATLAS_HOME_IS_DEFAULT:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture-atlas-2"
        make_fixture_project(fixture, project="demo-proj-2", ticket_id="T-902")
        decoy = Path(tmp) / "decoy-legacy"
        make_fixture_project(decoy, project="demo-proj-2", ticket_id="T-903")
        # ATLAS_HOME is only ever consulted by atlas_paths_home(); overriding it here to a
        # decoy directory must have no effect, because the guard requires the LITERAL real
        # default ($HOME/atlas) before Atlas is even considered — an override already
        # takes the isolated/legacy branch on its own. This proves the two branches can
        # never merge: whichever one runs, it runs to the exclusion of the other.
        r = run_cli(["list", "--project", "demo-proj-2"], atlas_home=fixture,
                    extra_env={"ATLAS_HOME": str(decoy)})
        chk("with ATLAS_HOME overridden, resolution stays inside ONE root — the decoy's "
            "own ticket, not a merge with the ATLAS_HOME fixture",
            "T-903" in r.stdout and "T-902" not in r.stdout)
else:
    chk("ATLAS_HOME is not the real default on this run — skipped (not a failure)", True)

t("`atlas tickets`: list/doctor/show see the same root (single projects_root per invocation)")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-atlas-3"
    make_fixture_project(fixture, project="demo-proj-3", ticket_id="T-904")
    r_list = run_cli(["list", "--project", "demo-proj-3"], atlas_home=fixture)
    r_show = run_cli(["show", "T-904"], atlas_home=fixture)
    r_doctor = run_cli(["doctor", "--project", "demo-proj-3"], atlas_home=fixture)
    chk("list sees it", "T-904" in r_list.stdout)
    chk("show sees it", r_show.returncode == 0 and "T-904" in r_show.stdout)
    chk("doctor runs against the same fixture (0 errors — the fixture ticket is well-formed)",
        r_doctor.returncode == 0)

t("`atlas tickets new`/`checkpoint`/`log` write to the same root reads came from")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-atlas-4"
    (fixture / "projects" / "demo-proj-4").mkdir(parents=True)
    r_new = run_cli(["new", "--project", "demo-proj-4", "--title", "fixture write test",
                     "--priority", "level_3", "--goal", "prove write-root parity",
                     "--requirement", "REQ-FIX", "--next-action", "n/a"],
                    atlas_home=fixture)
    chk("new succeeds", r_new.returncode == 0)
    written = list((fixture / "projects" / "demo-proj-4" / "tickets").glob("T-*/task.md"))
    chk("the new ticket file was written INSIDE the fixture (not the real workspace)",
        len(written) == 1)
    if written:
        new_id = written[0].parent.name
        r_cp = run_cli(["checkpoint", new_id, "--note", "fixture checkpoint"],
                       atlas_home=fixture)
        chk("checkpoint on the same fixture succeeds", r_cp.returncode == 0)
        chk("checkpoint content landed in the same file (no second copy created elsewhere)",
            "fixture checkpoint" in written[0].read_text())
        r_show2 = run_cli(["show", new_id], atlas_home=fixture)
        chk("a fresh `show` against the same ATLAS_HOME reads back what checkpoint wrote",
            "fixture checkpoint" in r_show2.stdout)

t("malformed canonical root: `atlas tickets` fails clearly instead of silently reading the "
  "legacy root")
if REAL_ATLAS_HOME_IS_DEFAULT:
    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture-malformed"
        fixture.mkdir(parents=True)
        (fixture / "projects").write_text("not a directory")  # malformed on purpose
        r = run_cli(["list", "--project", "atlas"], atlas_home=fixture)
        chk("exits non-zero", r.returncode != 0)
        chk("never silently falls back to the real legacy root's tickets",
            "T-045" not in r.stdout and "T-040" not in r.stdout)
        chk("reports the failure rather than a stack trace",
            "✗" in r.stdout or "✗" in r.stderr or "no single answer" in r.stdout + r.stderr)
else:
    chk("ATLAS_HOME is not the real default on this run — skipped (not a failure)", True)

t("legacy AIOS-* ids remain readable once they live in the selected canonical root "
  "(fixture-proven, no dependency on the real workspace's history)")
with tempfile.TemporaryDirectory() as tmp:
    fixture = Path(tmp) / "fixture-legacy-id"
    make_fixture_project(fixture, project="demo-proj-5", ticket_id="AIOS-901")
    r = run_cli(["show", "AIOS-901"], atlas_home=fixture)
    chk("an AIOS-###-shaped id resolves through the same canonical-root logic as a T-### id",
        r.returncode == 0 and "AIOS-901" in r.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
