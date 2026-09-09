#!/usr/bin/env python3
"""tests/test-agentic-permission.py — T-102: the Agentic Permission Envelope.

Proves `atlas agentic check`/`approve` — the permission boundary built on top of T-101's
run envelope, per the owner decisions recorded in T-102's Log (D1-D5):

  D1  profile -> rung: observer=observe, planner=propose, executor=execute,
      reviewer=execute-with-approval; 'admin' is NOT an alias of 'autonomous' — it is a
      permission-management-only role that may never invoke a capability directly.
  D2  a run's declared grant only ever LOWERS a capability's own public maximum
      (`capability.authority`), never raises it.
  D3  the private grant is always resolved per-action against the target capability, via
      `atlas-capability`'s own `granted_rung()` — no second, profile-keyed ledger.
  D4  an action is in scope only when its declared target scope exactly equals the run's
      `claims.scope` — no hierarchy, no subset matching.
  D5  "action escalation" is the exact authority-vs-grant comparison
      `atlas capability invoke` already makes, reused (imported), not reimplemented.

Also proves: unknown profile/capability/action/grant/scope is denied, not guessed; a
denial and an approval both leave a reason in the run's own `permission_log`; approval
evidence is recorded at most once and never inferred; and a denied action never reaches
the downstream executor (`atlas capability invoke`), verified by checking for that
command's own dry-run output text, which appears only when `check --execute` was allowed.

Uses a throwaway ATLAS_HOME/ATLAS_HOME and a fixture capability registry (ATLAS_CAPABILITIES)
with one operation at each of the four real, grantable authority rungs — never the real
`capabilities/browser`, so nothing here depends on that manifest's own shape. Nothing here
touches the real workspace.
"""
import json, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli" / "atlas-agentic"

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


FIXTURE_MANIFEST = """\
plugin: fixture
name: T-102 fixture capability
contract: 1
capability: { authority: execute-with-approval }
operations:
  look:
    summary: read-only
    command: noop
    authority: observe
  draft:
    summary: prepare without performing
    command: noop
    authority: propose
  act:
    summary: perform a reversible action
    command: noop
    authority: execute
  ship:
    summary: perform an irreversible action
    command: noop
    authority: execute-with-approval
"""


def make_fixtures(home):
    caps = home / "capabilities" / "fixture"
    caps.mkdir(parents=True)
    (caps / "capability.yaml").write_text(FIXTURE_MANIFEST)
    noop = caps / "noop"
    noop.write_text("#!/bin/sh\necho ok\n")
    noop.chmod(0o755)
    return home / "capabilities"


def write_ledger(home, **grants):
    p = home / "internal" / "config" / "authority.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["default: observe", "capabilities:"]
    for cap, rung in grants.items():
        lines.append(f"  {cap}: {rung}")
    if not grants:
        lines.append("  {}")
    p.write_text("\n".join(lines) + "\n")


def run_agentic(home, caps_dir, *args):
    return subprocess.run(
        [str(CLI), *args], cwd=str(home),
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home),
            "ATLAS_CAPABILITIES": str(caps_dir), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def create(home, caps_dir, profile, grant, scope="T-102", ticket="T-102"):
    r = run_agentic(home, caps_dir, "create", "--ticket", ticket, "--summary", "x",
                    "--profile", profile, "--grant", grant, "--scope", scope)
    assert r.returncode == 0, r.stdout + r.stderr
    files = list((home / "runtime" / "agentic").glob("*.json"))
    return max(files, key=lambda p: p.stat().st_mtime).stem


def log_tail(home, run_id):
    rec = json.loads((home / "runtime" / "agentic" / f"{run_id}.json").read_text())
    return rec["permission_log"][-1]


# =========================================================================================
t("observer — read-only behavior: allowed at 'observe', denied above it")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")  # ledger wide open; profile is the limit
    run_id = create(home, caps, "observer", "observe")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.look", "--scope", "T-102")
    chk("observer may read", r.returncode == 0 and "allowed" in r.stdout)
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    chk("observer may not act (execute exceeds its max)", r.returncode == 5)
    chk("denial names the profile ceiling", "profile 'observer'" in r.stdout)

t("planner — allowed to plan (propose), denied to act (execute)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "planner", "propose")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.draft", "--scope", "T-102")
    chk("planner may draft (propose)", r.returncode == 0)
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    chk("planner may not act (execute exceeds propose)", r.returncode == 5)

t("executor — denied without the required grant, even with the right profile and ceiling")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home)  # nothing granted -> everything defaults to 'observe'
    run_id = create(home, caps, "executor", "execute")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    chk("denied — profile and ceiling both allow 'execute', but the ledger does not",
        r.returncode == 5)
    chk("reason names the ledger grant, not the profile or ceiling",
        "granted 'observe'" in r.stdout)
    write_ledger(home, fixture="execute")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    chk("allowed once the ledger actually grants it", r.returncode == 0)

t("reviewer — denied with no approval, allowed once approval is recorded")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "reviewer", "execute-with-approval")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.ship", "--scope", "T-102")
    chk("denied: missing approval evidence", r.returncode == 5
        and "missing approval evidence" in r.stdout)
    r = run_agentic(home, caps, "approve", run_id, "--owner-words", "reviewed and approved for this test")
    chk("approval recorded", r.returncode == 0)
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.ship", "--scope", "T-102")
    chk("allowed once approval evidence is recorded", r.returncode == 0)
    r = run_agentic(home, caps, "approve", run_id, "--owner-words", "trying again")
    chk("a second approval attempt is refused, not overwritten", r.returncode != 0)

t("admin — may never invoke a capability directly, regardless of grant or approval")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "admin", "execute-with-approval")
    run_agentic(home, caps, "approve", run_id, "--owner-words", "owner approved")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.look", "--scope", "T-102")
    chk("admin denied even for the lowest-authority action, even with approval recorded",
        r.returncode == 5 and "permission-management role only" in r.stdout)

t("admin — permission-management actions: denied without approval, allowed once recorded, denied for any other profile")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    run_id = create(home, caps, "admin", "observe")
    r = run_agentic(home, caps, "check", run_id, "--permission-change")
    chk("denied: permission changes are never auto-approved", r.returncode == 5
        and "never be auto-approved" in r.stdout)
    run_agentic(home, caps, "approve", run_id, "--owner-words", "owner approved this permission change")
    r = run_agentic(home, caps, "check", run_id, "--permission-change")
    chk("allowed once approval evidence is recorded", r.returncode == 0)

    other_run = create(home, caps, "executor", "execute")
    write_ledger(home, fixture="execute")
    run_agentic(home, caps, "approve", other_run, "--owner-words", "owner approved")
    r = run_agentic(home, caps, "check", other_run, "--permission-change")
    chk("a non-admin profile may never perform a permission-management action, even approved",
        r.returncode == 5 and "only 'admin' may" in r.stdout)

# =========================================================================================
t("unknown profile is denied at creation, never guessed")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    r = run_agentic(home, caps, "create", "--ticket", "T-102", "--summary", "x",
                    "--profile", "superuser", "--scope", "T-102")
    chk("refused", r.returncode != 0)
    chk("names the unknown profile", "superuser" in r.stdout)

t("unknown grant is denied at creation")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    r = run_agentic(home, caps, "create", "--ticket", "T-102", "--summary", "x",
                    "--grant", "yolo", "--scope", "T-102")
    chk("refused", r.returncode != 0)

t("unknown capability is denied")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "executor", "execute")
    r = run_agentic(home, caps, "check", run_id, "--capability", "nosuch.op", "--scope", "T-102")
    chk("denied", r.returncode == 5 and "unknown capability" in r.stdout)

t("unknown action (undeclared operation) is denied")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "executor", "execute")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.nosuchop", "--scope", "T-102")
    chk("denied", r.returncode == 5 and "unknown action" in r.stdout)

t("scope escalation is denied — no hierarchy, exact match only")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "executor", "execute", scope="T-102")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-999")
    chk("a different target scope is denied", r.returncode == 5
        and "scope escalation" in r.stdout)
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-1029")
    chk("a scope that merely starts with the run's scope is still denied (no prefix/subset match)",
        r.returncode == 5)

t("action escalation — the run's declared ceiling may only lower the capability's public maximum, never raise it")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    # 'autonomous' is still a syntactically real rung (create doesn't refuse it — nothing
    # about it is malformed), but the fixture's own manifest ceiling is
    # execute-with-approval, one rung below it — D2 says a declared ceiling may only ever
    # lower that maximum, never raise it, so the check itself must refuse it.
    run_id = create(home, caps, "reviewer", "autonomous")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.ship", "--scope", "T-102")
    chk("denied: a declared ceiling above the capability's own public maximum is refused, "
        "never silently capped", r.returncode == 5
        and "exceeds" in r.stdout and "public maximum" in r.stdout)

t("action escalation — 'inherit' takes the capability's own maximum, not the profile's")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute-with-approval")
    run_id = create(home, caps, "executor", "inherit")
    r = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    chk("executor + inherit still allows 'execute' (within both profile max and ledger)",
        r.returncode == 0)

# =========================================================================================
t("denial reason is recorded in the run's own permission_log")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home)
    run_id = create(home, caps, "observer", "observe")
    run_agentic(home, caps, "check", run_id, "--capability", "fixture.act", "--scope", "T-102")
    entry = log_tail(home, run_id)
    chk("last log entry is a deny", entry["decision"] == "deny")
    chk("reason is non-empty and explains the denial", "profile" in entry["reason"].lower())
    chk("entry names the capability and profile", entry["capability"] == "fixture.act"
        and entry["profile"] == "observer")

t("approval evidence is recorded in the run's own approval field, immutable once set")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    run_id = create(home, caps, "reviewer", "execute-with-approval")
    run_agentic(home, caps, "approve", run_id, "--owner-words", "the exact evidence text")
    rec = json.loads((home / "runtime" / "agentic" / f"{run_id}.json").read_text())
    chk("approval.approval is 'recorded'", rec["approval"]["approval"] == "recorded")
    chk("approval.owner_words carries the exact text", rec["approval"]["owner_words"]
        == "the exact evidence text")
    chk("approval.approved_at is set", bool(rec["approval"]["approved_at"]))

# =========================================================================================
t("downstream execution is never reached after a denial, only after an allow")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    caps = make_fixtures(home)
    write_ledger(home, fixture="execute")
    run_id = create(home, caps, "executor", "execute")
    denied = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act",
                         "--scope", "T-999", "--execute")
    chk("denied, exit 5", denied.returncode == 5)
    chk("the downstream capability CLI's own dry-run output never appears on a denial",
        "dry run" not in denied.stdout and "invocable" not in denied.stdout)
    allowed = run_agentic(home, caps, "check", run_id, "--capability", "fixture.act",
                          "--scope", "T-102", "--execute")
    chk("allowed, exit 0", allowed.returncode == 0)
    chk("the downstream capability CLI actually ran, in --dry-run, only now",
        "dry run" in allowed.stdout and "invocable" in allowed.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
