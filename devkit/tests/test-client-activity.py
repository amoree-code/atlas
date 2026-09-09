#!/usr/bin/env python3
"""tests/test-client-activity.py — T-125: client-neutral live-activity records, gated on
successful admission. Same fixture pattern as `test-admission-boundary.py`. Runs the same
contract twice — once as `claude-code`, once as a generic `some-other-client` — to prove
nothing here special-cases the first registered client.
"""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CLI = Path(__file__).resolve().parents[2] / "cli"
sys.path.insert(0, str(CLI))
import atlas_coordination as coord
import atlas_admission as admission
import atlas_client_activity as activity

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


def new_home(ticket_id):
    tmp = tempfile.mkdtemp(prefix="t125-activity-")
    root = Path(tmp)
    d = root / "projects" / "atlas" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nkind: ticket\nnamespace: atlas.ticket\nid: {ticket_id}\n"
        f"title: fixture ticket for activity tests\nstate: active\nproject: atlas\n"
        f"opened_at: 2026-09-09 12:00 PM\nupdated_at: 2026-09-09 12:00 PM\n"
        f"artifacts: []\n---\n# fixture\n")
    os.environ["ATLAS_HOME"] = str(root)
    return root, d


_run_seq = [0]


def run_id():
    _run_seq[0] += 1
    return f"agentic-20260909-130000-{_run_seq[0]:06x}"


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
        "created_at": "2026-09-09 13:00:00", "updated_at": "2026-09-09 13:00:00",
    }
    p.write_text(json.dumps(rec))
    return rec


def admit(ticket, client, session, scope):
    root, task_dir = new_home(ticket)
    key = f"lease-{client}-{session}-{time.time_ns()}"
    lease = coord.lease_acquire(task_dir, ticket, client, session, "inv-1", 60, key)
    ckey = f"claim-{client}-{session}-{time.time_ns()}"
    coord.claim_acquire(task_dir, ticket, lease["lease_id"], scope, client, session, ckey)
    rid = run_id()
    write_run(root, rid, ticket, client, session, scope, lease["lease_id"])
    opened = admission.admit_open(task_dir, ticket, rid, scope, client, session,
                                  f"idem-{client}-{session}")
    return root, task_dir, opened


def run_full_contract(ticket, client, session, scope):
    t(f"contract for client={client!r} session={session!r}")
    root, task_dir, opened = admit(ticket, client, session, scope)

    rec = activity.activity_start(opened, client_name=f"{client} display name",
                                  agent_id="agent-1", provider="anthropic",
                                  expires_in_seconds=60)
    expected_fields = {"client_id", "client_name", "agent_id", "provider", "session_id",
                       "ticket", "scope", "lease_id", "last_seen", "expiry", "status"}
    chk("activity_start records every required field",
        expected_fields.issubset(rec.keys()))
    chk("activity_start sets status active", rec.get("status") == "active")
    chk("activity_start records the caller's client_id/session_id",
        rec.get("client_id") == client and rec.get("session_id") == session)
    chk("activity_start records ticket/scope/lease_id from the admission object",
        rec.get("ticket") == ticket and rec.get("scope") == scope and
        rec.get("lease_id") == opened.get("lease_id"))

    status = activity.activity_status(client, session)
    chk("activity_status reads back active", status is not None and
        status.get("status") == "active")

    rows = activity.list_activity(ticket)
    chk("list_activity finds exactly one row for this ticket", len(rows) == 1)
    chk("list_activity row matches client_id", rows[0].get("client_id") == client)

    first_last_seen = status["last_seen"]
    time.sleep(0.01)
    hb = activity.activity_heartbeat(client, session)
    chk("activity_heartbeat advances last_seen", hb.get("last_seen") != first_last_seen)
    chk("activity_heartbeat leaves status active", hb.get("status") == "active")

    try:
        activity.activity_start({"not": "open"}, client_name="x", agent_id="a",
                                provider="p", expires_in_seconds=60)
        chk("activity_start refused on a non-open admission object", False)
    except coord.CoordinationError as e:
        chk("activity_start refused on a non-open admission object",
            "state == 'open'" in str(e))

    forced = dict(hb)
    forced["expiry"] = coord.iso(coord.now_utc() - datetime.timedelta(seconds=10))
    coord._atomic_write_json(activity._activity_path(client, session), forced)
    stale_read = activity.activity_status(client, session)
    chk("forced-expired expiry reads back as status stale",
        stale_read.get("status") == "stale")
    on_disk, _ = coord._read_json(activity._activity_path(client, session))
    chk("the on-disk record itself was never mutated by the stale read",
        on_disk.get("status") == "active")

    closed = activity.activity_close(client, session)
    chk("activity_close succeeds on a stale-derived record via explicit close",
        closed.get("status") == "closed")
    try:
        activity.activity_close(client, session)
        chk("double-close refused", False)
    except coord.CoordinationError as e:
        chk("double-close refused", "already closed" in str(e))
    try:
        activity.activity_heartbeat(client, session)
        chk("heartbeat refused on a closed record", False)
    except coord.CoordinationError as e:
        chk("heartbeat refused on a closed record", "no active activity record" in str(e))

    return root, task_dir


run_full_contract("T-950", activity.CLIENT_CLAUDE_CODE, "s1", "claude/scope.txt")
run_full_contract("T-951", "some-other-client", "s2", "generic/scope.txt")

# =========================================================================================
t("no activity record exists for a session that was never admitted")
_, no_admit_dir = new_home("T-952")
missing = activity.activity_status("nobody", "no-session")
chk("activity_status returns None when no record was ever started", missing is None)

# =========================================================================================
t("atlas-activity CLI read path additively lists client activity")
root, task_dir, opened = admit("T-953", activity.CLIENT_CLAUDE_CODE, "s3", "cli/scope.txt")
activity.activity_start(opened, client_name="Claude Code", agent_id="agent-9",
                        provider="anthropic", expires_in_seconds=120)
cli = Path(__file__).resolve().parents[2] / "cli" / "atlas-activity"
r = subprocess.run([str(cli), "--project", "atlas", "--json"],
                   env={**os.environ, "ATLAS_HOME": str(root)},
                   capture_output=True, text=True)
chk("atlas-activity CLI exits 0", r.returncode == 0)
out = json.loads(r.stdout)
row = next((row for row in out["tickets"] if row["ticket"] == "T-953"), None)
chk("atlas-activity CLI output includes the fixture ticket", row is not None)
chk("atlas-activity CLI additive 'clients' field lists the started client",
    row is not None and any(c["client_id"] == "claude-code" and c["status"] == "active"
                            for c in row["clients"]))

# =========================================================================================
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
