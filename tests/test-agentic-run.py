#!/usr/bin/env python3
"""tests/test-agentic-run.py — T-101: the Agentic JSON Run Envelope.

Proves `atlas agentic create/show/validate/list` and the contract they implement
(schemas/agentic-run.schema.md): a run can actually be created, inspected and validated,
`goal.ticket` is stored and checked as an opaque identifier only (never a copy of the
ticket's title/status/checklist), an invalid envelope (bad lifecycle status, budget over
max, malformed run id/timestamp) is refused or reported, and every generated record lives
only under `$ATLAS_HOME/runtime/agentic/`. Nothing here touches the real workspace — every
scenario runs against a throwaway ATLAS_HOME, exactly like tests/test-ticket-lifecycle.py.
"""
import json, re, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli" / "atlas-agentic"
SCHEMA = REPO / "schemas" / "agentic-run.schema.md"

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


def run_agentic(home, *args):
    return subprocess.run(
        [str(CLI), *args], cwd=str(home),
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def created_run_id(home):
    files = list((home / "runtime" / "agentic").glob("*.json"))
    assert len(files) == 1, f"expected exactly one run file, found {len(files)}"
    return files[0].stem


# =========================================================================================
t("the contract document itself still declares every field and lifecycle state")
schema = SCHEMA.read_text()
for token in ('"goal"', '"actor"', '"stage"', '"workflow"', '"packet"', '"budget"',
             '"permissions"', '"claims"', '"stop_conditions"'):
    chk(f"contract mentions {token}", token in schema)
for state in ("active", "paused", "blocked", "completed", "failed", "stopped"):
    chk(f"contract lists lifecycle state '{state}'", state in schema)
chk("contract says ticket records remain authoritative",
    "ticket records remain authoritative" in schema.lower())
chk("contract says this is not a workflow engine", "workflow engine" in schema.lower())

# =========================================================================================
t("create — a run can actually be created, and only under runtime/agentic/")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    r = run_agentic(home, "create", "--ticket", "T-101",
                    "--summary", "Write the run envelope contract from the approved Agentic design.")
    chk("exits 0", r.returncode == 0)
    chk("reports the run as created", "created" in r.stdout)
    chk("goal is echoed as an opaque reference, not resolved", "opaque reference" in r.stdout)
    run_id = created_run_id(home)
    chk("run_id matches the documented shape",
        re.match(r"^agentic-\d{8}-\d{6}-[0-9a-f]{6}$", run_id) is not None)
    chk("nothing was written outside runtime/agentic/",
        list(home.rglob("*.json")) == [home / "runtime" / "agentic" / f"{run_id}.json"])

t("show — a created run can actually be inspected, and stays opaque about the ticket")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "do the work")
    run_id = created_run_id(home)
    r = run_agentic(home, "show", run_id)
    chk("exits 0", r.returncode == 0)
    data = json.loads(r.stdout)
    chk("goal.ticket is exactly the opaque id, nothing appended",
        data["goal"]["ticket"] == "T-101")
    chk("no ticket title, checklist or status content leaked into the envelope",
        "checklist" not in json.dumps(data).lower()
        and "Duplicate Ticket Guard" not in json.dumps(data))
    chk("carries every contract field",
        set(("run_id", "goal", "actor", "stage", "workflow", "packet", "budget",
            "permissions", "claims", "stop_conditions", "status", "created_at",
            "updated_at")) <= set(data.keys()))

t("show — refuses a run id that does not exist")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    r = run_agentic(home, "show", "agentic-20260101-000000-abcdef")
    chk("refused, not a crash", r.returncode != 0)
    chk("names the missing run", "no such run" in r.stderr)

# =========================================================================================
t("validate — a freshly created run validates clean")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "AIOS-001", "--summary", "legacy id also accepted")
    run_id = created_run_id(home)
    r = run_agentic(home, "validate", run_id)
    chk("exits 0", r.returncode == 0)
    chk("reports valid", "valid" in r.stdout)

t("validate — budget.steps_used exceeding steps_max is caught, not silently accepted")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "x", "--steps-max", "3")
    run_id = created_run_id(home)
    p = home / "runtime" / "agentic" / f"{run_id}.json"
    rec = json.loads(p.read_text())
    rec["budget"]["steps_used"] = 999
    p.write_text(json.dumps(rec, indent=2))
    r = run_agentic(home, "validate", run_id)
    chk("refused", r.returncode != 0)
    chk("names the exact rule broken",
        "steps_used must not exceed" in r.stdout)

t("validate — an invalid lifecycle status is caught")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "x")
    run_id = created_run_id(home)
    p = home / "runtime" / "agentic" / f"{run_id}.json"
    rec = json.loads(p.read_text())
    rec["status"] = "in-orbit"
    p.write_text(json.dumps(rec, indent=2))
    r = run_agentic(home, "validate", run_id)
    chk("refused", r.returncode != 0)
    chk("names the bad status", "'status'" in r.stdout and "in-orbit" in r.stdout)

t("validate — an empty stop_conditions list is caught")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "x")
    run_id = created_run_id(home)
    p = home / "runtime" / "agentic" / f"{run_id}.json"
    rec = json.loads(p.read_text())
    rec["stop_conditions"] = []
    p.write_text(json.dumps(rec, indent=2))
    r = run_agentic(home, "validate", run_id)
    chk("refused", r.returncode != 0)
    chk("names the empty stop_conditions", "stop_conditions" in r.stdout)

t("validate — a malformed timestamp is caught")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "x")
    run_id = created_run_id(home)
    p = home / "runtime" / "agentic" / f"{run_id}.json"
    rec = json.loads(p.read_text())
    rec["updated_at"] = "not-a-timestamp"
    p.write_text(json.dumps(rec, indent=2))
    r = run_agentic(home, "validate", run_id)
    chk("refused", r.returncode != 0)
    chk("names the bad timestamp field", "'updated_at'" in r.stdout)

# =========================================================================================
t("create — refuses an invalid ticket id, nothing written")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    r = run_agentic(home, "create", "--ticket", "not-a-ticket", "--summary", "x")
    chk("refused", r.returncode != 0)
    chk("nothing was written", not (home / "runtime" / "agentic").exists()
        or not any((home / "runtime" / "agentic").glob("*.json")))

t("create — refuses a missing --summary, nothing written")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    r = run_agentic(home, "create", "--ticket", "T-101")
    chk("refused", r.returncode != 0)
    chk("nothing was written", not (home / "runtime" / "agentic").exists()
        or not any((home / "runtime" / "agentic").glob("*.json")))

# =========================================================================================
t("list — every created run is listed, with status, stage and its opaque ticket reference")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    run_agentic(home, "create", "--ticket", "T-101", "--summary", "one")
    run_agentic(home, "create", "--ticket", "T-103", "--summary", "two")
    r = run_agentic(home, "list")
    chk("exits 0", r.returncode == 0)
    chk("both tickets are named", "T-101" in r.stdout and "T-103" in r.stdout)
    chk("both are shown active", r.stdout.count("active") == 2)

t("list — an empty runtime/agentic reports cleanly, not an error")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    r = run_agentic(home, "list")
    chk("exits 0", r.returncode == 0)
    chk("reports no runs rather than crashing", "no Agentic runs" in r.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
