#!/usr/bin/env python3
"""tests/test-admission-boundary.py — T-125: fail-closed admission boundary.

Focused (not exhaustive) scenarios against a disposable `tempfile.mkdtemp()` ATLAS_HOME,
same fixture shape as `test-coordinator-conflict-protection.py`. Exercises the real
`atlas_coordination.py` / `atlas_admission.py` / `atlas-agentic` — nothing here is mocked.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI))
import atlas_coordination as coord
import atlas_admission as admission

G, Y, R, D, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = Y = R = D = X = ""
passed = failed = 0


def chk(desc, ok):
    global passed, failed
    if ok:
        print(f"  {G}PASS{X} {desc}"); passed += 1
    else:
        print(f"  {R}FAIL{X} {desc}"); failed += 1


def t(label):
    print(f"\n{D}— {label}{X}")


def new_home(ticket_id="T-900"):
    tmp = tempfile.mkdtemp(prefix="t125-admission-")
    root = Path(tmp)
    d = root / "projects" / "atlas" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nkind: ticket\nnamespace: atlas.ticket\nid: {ticket_id}\n"
        f"title: fixture ticket for admission tests\nstate: active\nproject: atlas\n"
        f"opened_at: 2026-09-09 12:00 PM\nupdated_at: 2026-09-09 12:00 PM\n"
        f"artifacts: []\n---\n# fixture\n")
    os.environ["ATLAS_HOME"] = str(root)
    return root, d


_run_seq = [0]


def run_id():
    _run_seq[0] += 1
    return f"agentic-20260909-120000-{_run_seq[0]:06x}"


def write_run(root, run_id_, ticket, client, session, scope, lease_id, status="active"):
    p = root / "runtime" / "agentic" / f"{run_id_}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "run_id": run_id_,
        "goal": {"ticket": ticket, "summary": "fixture run"},
        "actor": {"client": client, "session_id": session},
        "stage": "implement", "workflow": "fixture",
        "packet": {"id": "packet-1", "kind": "context", "revision": 1},
        "budget": {"steps_max": 10, "steps_used": 0},
        "permissions": {"profile": "executor", "grant": "inherit"},
        "claims": {"scope": scope, "lease": lease_id},
        "stop_conditions": ["fixture stop"],
        "status": status,
        "created_at": "2026-09-09 12:00:00", "updated_at": "2026-09-09 12:00:00",
    }
    p.write_text(json.dumps(rec))
    return rec


def acquire_lease(task_dir, task_id, client="claude-code", session="s1", ttl=60, key=None):
    key = key or f"lease-{client}-{session}-{time.time_ns()}"
    return coord.lease_acquire(task_dir, task_id, client, session, "inv-1", ttl, key)


def acquire_claim(task_dir, task_id, lease_id, raw_path, client="claude-code", session="s1",
                  key=None):
    key = key or f"claim-{client}-{session}-{time.time_ns()}"
    return coord.claim_acquire(task_dir, task_id, lease_id, raw_path, client, session, key)


def full_admission_fixture(ticket="T-900", client="claude-code", session="s1",
                           scope="some/scope/file.txt", status="active"):
    root, task_dir = new_home(ticket)
    lease = acquire_lease(task_dir, ticket, client=client, session=session)
    acquire_claim(task_dir, ticket, lease["lease_id"], scope, client=client, session=session)
    rid = run_id()
    write_run(root, rid, ticket, client, session, scope, lease["lease_id"], status=status)
    return root, task_dir, rid, lease


# =========================================================================================
t("1 — valid admission passes verify_admission and admit_open")
root, task_dir, rid, lease = full_admission_fixture()
rec, lease_id = admission.verify_admission(task_dir, "T-900", rid, "some/scope/file.txt",
                                           "claude-code", "s1")
chk("verify_admission returns the run record", rec.get("run_id") == rid)
chk("verify_admission returns the bound lease id", lease_id == lease["lease_id"])

opened = admission.admit_open(task_dir, "T-900", rid, "some/scope/file.txt", "claude-code",
                              "s1", "idem-1")
chk("admit_open succeeds and records state=open", opened.get("state") == "open")
chk("admit_open records the lease id", opened.get("lease_id") == lease["lease_id"])
chk("admit_open is not a replay the first time", opened.get("replay") is False)

# =========================================================================================
t("2 — admit_open idempotent replay on the identical repeated call")
opened2 = admission.admit_open(task_dir, "T-900", rid, "some/scope/file.txt", "claude-code",
                               "s1", "idem-1")
chk("repeated admit_open with same idempotency key replays, no re-verification error",
    opened2.get("replay") is True and opened2.get("state") == "open")

# =========================================================================================
t("3 — a second open attempt with a different idempotency key/scope is refused")
try:
    admission.admit_open(task_dir, "T-900", rid, "some/scope/file.txt", "claude-code", "s1",
                         "idem-2")
    chk("second distinct admit_open refused while one is already open", False)
except coord.CoordinationError as e:
    chk("second distinct admit_open refused while one is already open",
        "already open" in str(e))

# =========================================================================================
t("4 — admit_check on an open admission; refused after close")
checked = admission.admit_check("claude-code", "s1")
chk("admit_check succeeds while open", checked.get("state") == "open")

closed = admission.admit_close("claude-code", "s1")
chk("admit_close succeeds", closed.get("state") == "closed")
try:
    admission.admit_close("claude-code", "s1")
    chk("double-close refused", False)
except coord.CoordinationError as e:
    chk("double-close refused", "already closed" in str(e))
try:
    admission.admit_check("claude-code", "s1")
    chk("admit_check refused after close", False)
except coord.CoordinationError as e:
    chk("admit_check refused after close", "no open admission" in str(e))

# =========================================================================================
t("5 — missing run (well-formed but nonexistent run id) refused")
root2, task_dir2 = new_home("T-901")
lease2 = acquire_lease(task_dir2, "T-901")
acquire_claim(task_dir2, "T-901", lease2["lease_id"], "some/other.txt")
try:
    admission.verify_admission(task_dir2, "T-901", "agentic-20260909-120000-abcdef",
                               "some/other.txt", "claude-code", "s1")
    chk("nonexistent run refused", False)
except coord.CoordinationError as e:
    chk("nonexistent run refused", "could not load run" in str(e))

# =========================================================================================
t("6 — malformed run id (fails atlas-agentic's own regex, dies via SystemExit) refused")
try:
    admission.verify_admission(task_dir2, "T-901", "not a valid run id!!", "some/other.txt",
                               "claude-code", "s1")
    chk("malformed run id converted to CoordinationError, not a raw SystemExit", False)
except coord.CoordinationError as e:
    chk("malformed run id converted to CoordinationError, not a raw SystemExit",
        "could not load run" in str(e))
except SystemExit:
    chk("malformed run id converted to CoordinationError, not a raw SystemExit", False)

# =========================================================================================
t("7 — run not active (status=paused) refused")
root3, task_dir3, rid3, lease3 = full_admission_fixture(ticket="T-902",
                                                        scope="paused/file.txt",
                                                        status="paused")
try:
    admission.verify_admission(task_dir3, "T-902", rid3, "paused/file.txt", "claude-code",
                               "s1")
    chk("inactive run refused", False)
except coord.CoordinationError as e:
    chk("inactive run refused", "not active" in str(e))

# =========================================================================================
t("8 — actor identity mismatch refused")
root4, task_dir4, rid4, lease4 = full_admission_fixture(ticket="T-903",
                                                        scope="identity/file.txt")
try:
    admission.verify_admission(task_dir4, "T-903", rid4, "identity/file.txt", "codex", "s1")
    chk("wrong client refused", False)
except coord.CoordinationError as e:
    chk("wrong client refused", "bound to actor" in str(e))

try:
    admission.verify_admission(task_dir4, "T-903", rid4, "identity/file.txt", "claude-code",
                               "wrong-session")
    chk("wrong session refused", False)
except coord.CoordinationError as e:
    chk("wrong session refused", "bound to actor" in str(e))

# =========================================================================================
t("9 — ticket mismatch refused")
root5, task_dir5, rid5, lease5 = full_admission_fixture(ticket="T-904",
                                                        scope="ticket/file.txt")
try:
    admission.verify_admission(task_dir5, "T-905", rid5, "ticket/file.txt", "claude-code",
                               "s1")
    chk("ticket mismatch refused", False)
except coord.CoordinationError as e:
    chk("ticket mismatch refused", "bound to ticket" in str(e))

# =========================================================================================
t("10 — exact-scope mismatch (escape to an unclaimed sibling path) refused")
root6, task_dir6, rid6, lease6 = full_admission_fixture(ticket="T-906",
                                                        scope="scope/exact.txt")
try:
    admission.verify_admission(task_dir6, "T-906", rid6, "scope/other.txt", "claude-code",
                               "s1")
    chk("exact-scope escape refused", False)
except coord.CoordinationError as e:
    chk("exact-scope escape refused", "requires an exact match" in str(e))

# =========================================================================================
t("11 — no lease bound in claims.lease refused")
root7, task_dir7 = new_home("T-907")
lease7 = acquire_lease(task_dir7, "T-907")
acquire_claim(task_dir7, "T-907", lease7["lease_id"], "nolease/file.txt")
rid7 = run_id()
write_run(root7, rid7, "T-907", "claude-code", "s1", "nolease/file.txt", None)
try:
    admission.verify_admission(task_dir7, "T-907", rid7, "nolease/file.txt", "claude-code",
                               "s1")
    chk("missing lease-in-claims refused", False)
except coord.CoordinationError as e:
    chk("missing lease-in-claims refused", "no lease bound" in str(e))

# =========================================================================================
t("12 — dispatch-conflict-protection failure (lease id mismatch) refused")
root8, task_dir8 = new_home("T-908")
lease8 = acquire_lease(task_dir8, "T-908")
acquire_claim(task_dir8, "T-908", lease8["lease_id"], "conflict/file.txt")
rid8 = run_id()
write_run(root8, rid8, "T-908", "claude-code", "s1", "conflict/file.txt", "lease-bogus")
try:
    admission.verify_admission(task_dir8, "T-908", rid8, "conflict/file.txt", "claude-code",
                               "s1")
    chk("lease/claim binding mismatch refused via verify_dispatch_conflict_protection",
        False)
except coord.CoordinationError as e:
    chk("lease/claim binding mismatch refused via verify_dispatch_conflict_protection",
        "does not match the active lease" in str(e))

# =========================================================================================
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
