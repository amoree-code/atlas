#!/usr/bin/env python3
"""tests/test-admission-gate.py — T-125: the Claude Code `ai-admission-gate` PreToolUse hook.

Focused (not exhaustive) scenarios, same fixture shape as
`devkit/tests/test-admission-boundary.py`: a disposable `tempfile.mkdtemp()` ATLAS_HOME, the
real `atlas_coordination` / `atlas_admission` / `atlas-agentic` used in-process to set up
fixture state (lease, claim, run, admission), and the real hook script run as an actual
subprocess — never mocked — so what is proven here is what Claude Code itself would see on
stdout for a given PreToolUse payload.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "ai-admission-gate"
CLI = Path(__file__).resolve().parents[5] / "cli"
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


# --- fixture helpers, matching devkit/tests/test-admission-boundary.py exactly ----------
def new_home(ticket_id="T-950"):
    tmp = tempfile.mkdtemp(prefix="t125-gate-")
    root = Path(tmp)
    d = root / "projects" / "atlas" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nkind: ticket\nnamespace: atlas.ticket\nid: {ticket_id}\n"
        f"title: fixture ticket for admission-gate tests\nstate: active\nproject: atlas\n"
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


def full_admission_fixture(ticket, scope, client="claude-code", session="s1", status="active"):
    """Builds lease + claim + run + open admission, and returns everything a hook payload
    needs: root (for the absolute write path) and the session id."""
    root, task_dir = new_home(ticket)
    lease = acquire_lease(task_dir, ticket, client=client, session=session)
    acquire_claim(task_dir, ticket, lease["lease_id"], scope, client=client, session=session)
    rid = run_id()
    write_run(root, rid, ticket, client, session, scope, lease["lease_id"], status=status)
    admission.admit_open(task_dir, ticket, rid, scope, client, session, f"idem-{rid}")
    return root, task_dir, rid, lease


def run_hook(payload):
    """Runs the real hook script as a subprocess with the current (fixture) ATLAS_HOME,
    exactly the way Claude Code itself would invoke it. Returns the parsed
    permissionDecision, or None if the hook emitted nothing (the no-op path)."""
    r = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload),
                       capture_output=True, text=True, env=os.environ.copy())
    if not r.stdout.strip():
        return None, r
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"], r


def write_payload(session_id, file_path, tool_name="Write"):
    key = "notebook_path" if tool_name == "NotebookEdit" else "file_path"
    return {"tool_name": tool_name, "session_id": session_id,
            "tool_input": {key: file_path, "content": "x"}}


# =========================================================================================
t("1 — valid admitted write is allowed")
root, task_dir, rid, lease = full_admission_fixture("T-950", "gate/scope/file.txt")
target = str(root / "gate" / "scope" / "file.txt")
decision, r = run_hook(write_payload("s1", target))
chk("hook allows a write within the exact admitted scope", decision == "allow")
chk("hook exits 0", r.returncode == 0)

# =========================================================================================
t("2 — missing admission (never admitted) is denied")
root2, task_dir2 = new_home("T-951")
decision, r = run_hook(write_payload("never-admitted-session", str(root2 / "x.txt")))
chk("hook denies a write with no open admission", decision == "deny")

# =========================================================================================
t("3 — closed admission is denied")
root3, task_dir3, rid3, lease3 = full_admission_fixture("T-952", "gate/closed.txt",
                                                        session="s3")
admission.admit_close("claude-code", "s3")
target3 = str(root3 / "gate" / "closed.txt")
decision, r = run_hook(write_payload("s3", target3))
chk("hook denies a write once the admission has been closed", decision == "deny")

# =========================================================================================
t("4 — expired claim is denied at write time, not just at admission-open time")
root4, task_dir4, rid4, lease4 = full_admission_fixture("T-953", "gate/expiring.txt",
                                                        session="s4")
claim_path = coord._claim_path(coord.canonicalize_path("gate/expiring.txt"))
obj, _ = coord._read_json(claim_path)
obj["lease_expires_at"] = "2000-01-01T00:00:00+00:00"
coord._atomic_write_json(claim_path, obj)
target4 = str(root4 / "gate" / "expiring.txt")
decision, r = run_hook(write_payload("s4", target4))
chk("hook denies a write once the underlying claim has expired, proving live "
    "revalidation and not a cached admission flag", decision == "deny")

# =========================================================================================
t("5 — wrong session is denied")
root5, task_dir5, rid5, lease5 = full_admission_fixture("T-954", "gate/session.txt",
                                                        session="s5")
target5 = str(root5 / "gate" / "session.txt")
decision, r = run_hook(write_payload("some-other-session", target5))
chk("hook denies a write from a session with no admission of its own", decision == "deny")

# =========================================================================================
t("6 — out-of-scope path is denied")
root6, task_dir6, rid6, lease6 = full_admission_fixture("T-955", "gate/exact.txt",
                                                        session="s6")
target6 = str(root6 / "gate" / "sibling.txt")
decision, r = run_hook(write_payload("s6", target6))
chk("hook denies a write to a path outside the admitted exact scope", decision == "deny")

# =========================================================================================
t("7 — malformed input (unparsable JSON / missing fields) is denied")
r = subprocess.run([sys.executable, str(HOOK)], input="not json at all",
                   capture_output=True, text=True, env=os.environ.copy())
out = json.loads(r.stdout)
chk("hook denies unparsable stdin", out["hookSpecificOutput"]["permissionDecision"] == "deny")

root7, task_dir7, rid7, lease7 = full_admission_fixture("T-956", "gate/nofield.txt",
                                                        session="s7")
target7 = str(root7 / "gate" / "nofield.txt")
no_session_payload = {"tool_name": "Write", "tool_input": {"file_path": target7}}
decision, r = run_hook(no_session_payload)
chk("hook denies a Write payload missing session_id", decision == "deny")

no_path_payload = {"tool_name": "Write", "session_id": "s7", "tool_input": {}}
decision, r = run_hook(no_path_payload)
chk("hook denies a Write payload missing a target file path", decision == "deny")

# =========================================================================================
t("8 — a Read tool call is a pure no-op, never inspected or blocked")
decision, r = run_hook({"tool_name": "Read", "session_id": "s1",
                        "tool_input": {"file_path": "/anything"}})
chk("hook emits nothing for a Read tool call", decision is None and r.stdout.strip() == "")
chk("hook still exits 0 for a Read tool call", r.returncode == 0)

# =========================================================================================
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
