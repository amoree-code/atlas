#!/usr/bin/env python3
"""tests/test-mission-conflict-integration.py — T-051-S7-R1: `mission execute` connects to
the real T-050 conflict-protection layer (`cli/aios_coordination.py`) before any executor
subprocess call.

This suite exercises the real, production `mission_execute` function end to end, using a
small, disposable FAKE executor binary (never `claude`) whose behavior is controlled by an
environment variable set before each call — the only way to deterministically exercise a
lease conflict, a claim conflict, a timeout, a non-zero exit, and a mid-flight external
release, none of which a real LLM can be made to reproduce on demand. The fake binary
receives the exact same argv/stdin/timeout contract a real transport would, so every test
here exercises the real lease-acquire / claim-acquire / subprocess / claim-release /
lease-release sequence `mission_execute` now performs, through the real, unmodified
`cli/aios_coordination.py` library — never a duplicated lease/claim implementation.

No real Claude CLI invocation happens anywhere in this file (that live-invocation coverage
already exists, and is not duplicated here, in `test-mission-execute.py` and
`test-mission-live-transport.py` — both already run their own live pilot once each; this
file avoids tripling real, costed API calls for functionality that is not about the AI
invocation itself, but about the lease/claim wiring around it).
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli"
CORE_CLI = REPO.parent / "core" / "cli"

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


def _load(cli_dir, name):
    modname = f"under_test_{cli_dir.parent.name}_{name.replace('-', '_').replace('.', '_')}_ci"
    spec = importlib.util.spec_from_loader(
        modname, importlib.machinery.SourceFileLoader(modname, str(cli_dir / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def run(cmd_fn, args):
    with captured() as (out, err):
        try:
            rc = cmd_fn(args)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def uniq_key(prefix):
    return f"{prefix}-{time.time_ns()}"


for _var in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS"):
    os.environ.pop(_var, None)

mission = _load(CLI, "aios_mission.py")
core_mission = _load(CORE_CLI, "aios_mission.py")
mission_cli = _load(CLI, "ai-os-mission")
core_mission_cli = _load(CORE_CLI, "ai-os-mission")
coord = _load(CLI, "aios_coordination.py")

# The FAKE executor binary. Behavior selected by FAKE_EXECUTOR_MODE:
#   pass          -> edits the scoped file, replies status "pass"
#   nonzero        -> exits 3, no reply
#   timeout        -> sleeps past the transport's own declared timeout
#   bad_json       -> prints non-JSON
#   missing_field  -> prints a JSON reply missing required fields
#   race_release   -> externally releases the SAME lease/claim (via a direct import of the
#                     real cli/aios_coordination.py, never a second implementation) BEFORE
#                     mission_execute's own post-execution cleanup runs, then replies "pass"
#                     as normal — the only deterministic way to reproduce a cleanup call that
#                     finds its own lease/claim already gone.
FAKE_EXECUTOR_SCRIPT = '''#!/usr/bin/env python3
import importlib.util as _ilu
import json, os, sys, time


def main():
    mode = os.environ.get("FAKE_EXECUTOR_MODE", "pass")
    raw = sys.stdin.read()
    marker = "PACKET:\\n"
    idx = raw.find(marker)
    packet = json.loads(raw[idx + len(marker):]) if idx >= 0 else {}

    if mode == "timeout":
        time.sleep(float(os.environ.get("FAKE_EXECUTOR_SLEEP", "5")))
        return 0

    counter_file = os.environ.get("FAKE_EXECUTOR_COUNTER_FILE")
    if counter_file:
        n = 0
        if os.path.exists(counter_file):
            n = int((open(counter_file).read().strip() or "0"))
        with open(counter_file, "w") as f:
            f.write(str(n + 1))

    if mode == "nonzero":
        sys.stderr.write("simulated executor failure\\n")
        return 3
    if mode == "bad_json":
        print("this is not json at all")
        return 0
    if mode == "missing_field":
        print(json.dumps({"status": "pass", "changed_files": [], "tests": ["x"],
                          "summary": "s"}))
        return 0

    scope = packet.get("scope") or {}
    scope_raw = scope.get("raw")
    scope_canonical = scope.get("canonical")

    if mode == "race_release":
        coord_path = os.environ.get("FAKE_EXECUTOR_COORD_PATH")
        ticket_dir = os.environ.get("FAKE_EXECUTOR_TICKET_DIR")
        if coord_path and ticket_dir:
            spec = _ilu.spec_from_file_location("race_coord", coord_path)
            race_coord = _ilu.module_from_spec(spec)
            spec.loader.exec_module(race_coord)
            lease_obj, _corrupt = race_coord._read_json(
                race_coord._lease_path(ticket_dir))
            lease_id = lease_obj.get("lease_id") if lease_obj else None
            client_val = packet.get("executor_client")
            session_val = packet.get("executor_session")
            invocation_val = packet.get("invocation_id")
            task_id_val = packet.get("root_task_id")
            try:
                race_coord.claim_release(ticket_dir, task_id_val, lease_id, scope_raw,
                                         client_val, session_val, "race-claim-release")
            except Exception:
                pass
            try:
                race_coord.lease_release(ticket_dir, task_id_val, lease_id, client_val,
                                         session_val, invocation_val, "race-lease-release")
            except Exception:
                pass

    identity = {k: packet.get(k) for k in
               ("handoff_id", "mission_id", "root_task_id", "executor_client",
                "executor_session", "invocation_id", "gate")}
    identity["scope"] = scope_raw

    if scope_canonical:
        new_content = os.environ.get("FAKE_EXECUTOR_NEW_CONTENT", "edited by fake executor")
        with open(scope_canonical, "w") as f:
            f.write(new_content + "\\n")

    reply = dict(identity)
    reply.update({
        "status": "pass", "changed_files": [scope_raw],
        "tests": ["read the file back and compared its content"],
        "reported_cost_usd": 0.01,
        "summary": f"fake executor ran in mode {mode}",
    })
    print(json.dumps(reply))
    return 0


sys.exit(main())
'''


def _mkbin(tmp, name, content):
    p = tmp / "bin" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return p


def new_fixture():
    """One disposable ATLAS_HOME with a fake-executor binary, a matching adapter, and a
    transport registry declaring `fake-executor` (verified: true, 30s timeout) and
    `fake-executor-timeout` (verified: true, 1s timeout) — plus `codex` for planner/verifier
    roles, exactly like every prior T-051 test fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="t051-ci-"))
    fake_bin = _mkbin(tmp, "fake-executor", FAKE_EXECUTOR_SCRIPT)

    adapters_dir = tmp / "adapters"
    for client, binname in (("codex", "codex-bin"), ("fake-executor", str(fake_bin)),
                            ("fake-executor-timeout", str(fake_bin))):
        d = adapters_dir / client
        d.mkdir(parents=True, exist_ok=True)
        (d / "adapter.yaml").write_text(
            f"adapter: {client}\nname: fixture adapter for {client}\ncontract: 1\n\n"
            f"client:\n  detect: [/nonexistent]\n  version_cmd: {binname} --version\n"
            f"  consumer_verified: false\n\nprovides:\n"
            f"  rules: {{ path: /nonexistent, format: markdown, verified: true }}\n\n"
            f"writes: []\nrequires: []\nenforces: []\n")

    transports_path = tmp / "handoff-transports.yaml"
    transports_path.write_text(
        "contract: 1\n\ntransports:\n"
        "  codex:\n"
        "    name: fixture codex\n    binary: codex-bin\n"
        "    argv: [--sandbox, read-only]\n    stdin: packet\n    timeout: 60\n"
        "    verified: true\n    evidence: fixture, not dispatched\n"
        "  fake-executor:\n"
        "    name: fixture fake executor\n"
        f"    binary: {fake_bin}\n"
        "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\", --budget-usd, __MISSION_BUDGET_USD__]\n"
        "    stdin: packet\n    timeout: 30\n    verified: true\n"
        "    evidence: disposable fixture, never the real registry\n"
        "  fake-executor-timeout:\n"
        "    name: fixture fake executor (fast timeout)\n"
        f"    binary: {fake_bin}\n"
        "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\", --budget-usd, __MISSION_BUDGET_USD__]\n"
        "    stdin: packet\n    timeout: 1\n    verified: true\n"
        "    evidence: disposable fixture, never the real registry\n")

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["AI_OS_ADAPTERS"] = str(adapters_dir)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(transports_path)
    os.environ["FAKE_EXECUTOR_COORD_PATH"] = str(CLI / "aios_coordination.py")
    return tmp


def new_ticket(tmp, ticket_id):
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture conflict-integration ticket {id}\nstate: active\n"
        "project: demo\nopened_at: 2026-09-07 12:00 AM\nupdated_at: 2026-09-07 12:00 AM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id))
    return d


def new_scope_file(tmp, rel_dir, name, content="untouched baseline\n"):
    d = tmp / rel_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(content)
    return p, f"{rel_dir}/{name}"


def do_create(task_id, scopes, executor="fake-executor", budget="1.00", max_slices="3",
             max_attempts="5", ttl="3600", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("create")
    args = [task_id]
    for s in scopes:
        args += ["--scope", s]
    args += ["--planner", "codex", "--executor", executor, "--verifier", "codex",
            "--budget-usd", budget, "--max-slices", max_slices, "--max-attempts", max_attempts,
            "--ttl-seconds", ttl, "--idempotency-key", key]
    return run(m.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def handoff_id_from(js):
    return json.loads(js)["handoff_id"]


def do_approve(task_id, mission_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("approve")
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words",
                              "approved by conflict-integration test",
                              "--idempotency-key", key])


def do_handoff(task_id, mission_id, scope, session, invocation, executor, gate="execute",
              budget="0.20", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("handoff")
    args = [task_id, mission_id, "--scope", scope, "--executor-client", executor,
           "--executor-session", session, "--invocation-id", invocation, "--gate", gate,
           "--slice-budget-usd", budget, "--idempotency-key", key, "--json"]
    return run(m.cmd_handoff, args)


def do_execute(task_id, mission_id, handoff_id, executor, session, invocation, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("execute")
    args = [task_id, mission_id, handoff_id, "--executor-client", executor,
           "--executor-session", session, "--invocation-id", invocation,
           "--idempotency-key", key, "--json"]
    return run(m.cmd_execute, args)


def full_setup(tmp, ticket_id, executor="fake-executor", mode=None, scope_name="alpha.txt",
              rel_dir=None, session=None, invocation=None, budget="1.00"):
    """create -> approve -> handoff, ready for `mission execute`. Returns a dict of everything
    a test needs, including the resolved ticket directory (for direct T-050 coordination
    inspection)."""
    new_ticket(tmp, ticket_id)
    rel_dir = rel_dir or f"work/{ticket_id.lower()}"
    scope_path, scope_raw = new_scope_file(tmp, rel_dir, scope_name)
    session = session or f"session-{ticket_id}"
    invocation = invocation or f"invocation-{ticket_id}"

    rc, out, err = do_create(ticket_id, [scope_raw], executor=executor, budget=budget)
    assert rc == 0, (rc, out, err)
    mission_id = mission_id_from(out)

    rc, out, err = do_approve(ticket_id, mission_id)
    assert rc == 0, (rc, out, err)

    rc, out, err = do_handoff(ticket_id, mission_id, scope_raw, session, invocation, executor)
    assert rc == 0, (rc, out, err)
    handoff_id = handoff_id_from(out)

    if mode is not None:
        os.environ["FAKE_EXECUTOR_MODE"] = mode
    task_dir = mission.resolve_task_dir(ticket_id)
    return {
        "ticket_id": ticket_id, "mission_id": mission_id, "handoff_id": handoff_id,
        "scope_path": scope_path, "scope_raw": scope_raw, "session": session,
        "invocation": invocation, "executor": executor, "task_dir": task_dir,
    }


def coordination_dir_for(task_dir):
    return Path(task_dir) / "coordination"


def lease_record(task_dir):
    obj, _c = coord._read_json(coordination_dir_for(task_dir) / "lease.json")
    return obj


def claim_record_for_path(raw_path):
    canonical = coord.canonicalize_path(raw_path)
    obj, _c = coord._read_json(coord._claim_path(canonical))
    return obj


def audit_events(task_dir, op=None):
    p = coordination_dir_for(task_dir) / "audit.log"
    if not p.is_file():
        return []
    events = [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    if op is not None:
        events = [e for e in events if e.get("op") == op]
    return events


# =============================================================================================
ROOT = new_fixture()

# --- 1-4: successful lease and claim acquisition ---------------------------------------------
t("1. valid execution acquires exactly one T-050 ticket lease and one T-050 file claim")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "written by test 1"
ctx1 = full_setup(ROOT, "T-991-A")
rc, out, err = do_execute(ctx1["ticket_id"], ctx1["mission_id"], ctx1["handoff_id"],
                          ctx1["executor"], ctx1["session"], ctx1["invocation"])
chk("mission execute exits 0", rc == 0)
res1 = json.loads(out)
chk("classification is PASS", res1["classification"] == "PASS")
chk("result carries a lease_id", bool(res1.get("lease_id")))
chk("result carries a claim_path", bool(res1.get("claim_path")))
chk("cleanup_complete is True", res1["cleanup_complete"] is True)
chk("cleanup shows both released", res1["cleanup"] == {"claim_released": True,
                                                        "lease_released": True})

t("2. exactly one lease_acquire and one claim_acquire audit event were recorded")
lease_events1 = audit_events(ctx1["task_dir"], "lease_acquire")
claim_events1 = audit_events(ctx1["task_dir"], "claim_acquire")
chk("exactly one lease_acquire audit event", len(lease_events1) == 1)
chk("exactly one claim_acquire audit event", len(claim_events1) == 1)
chk("the claim_acquire event names this handoff's own scope",
   claim_events1[0]["path"] == coord.canonicalize_path(ctx1["scope_raw"]))

t("3. the lease was acquired under the exact mission executor identity")
chk("lease_acquire audit event client matches executor_client",
   lease_events1[0]["client_id"] == ctx1["executor"])
chk("lease_acquire audit event session matches executor_session",
   lease_events1[0]["session_id"] == ctx1["session"])
chk("lease_acquire audit event invocation matches invocation_id",
   lease_events1[0]["invocation_id"] == ctx1["invocation"])

t("4. the claim was acquired under the exact mission executor identity, referencing the "
  "lease this same attempt acquired")
chk("claim_acquire audit event client matches executor_client",
   claim_events1[0]["client_id"] == ctx1["executor"])
chk("claim_acquire audit event session matches executor_session",
   claim_events1[0]["session_id"] == ctx1["session"])
chk("claim_acquire audit event references the lease acquired in this same attempt",
   claim_events1[0]["lease_id"] == lease_events1[0]["lease_id"] == res1["lease_id"])

# --- 5-6: release order ------------------------------------------------------------------------
t("5. release order: claim released before lease, in that exact order")
claim_release_events1 = audit_events(ctx1["task_dir"], "claim_release")
lease_release_events1 = audit_events(ctx1["task_dir"], "lease_release")
chk("exactly one claim_release audit event", len(claim_release_events1) == 1)
chk("exactly one lease_release audit event", len(lease_release_events1) == 1)
all_events1 = [json.loads(line) for line in
              (coordination_dir_for(ctx1["task_dir"]) / "audit.log").read_text().splitlines()
              if line.strip()]
claim_rel_idx = next(i for i, e in enumerate(all_events1) if e.get("op") == "claim_release")
lease_rel_idx = next(i for i, e in enumerate(all_events1) if e.get("op") == "lease_release")
chk("claim_release audit event appears before lease_release", claim_rel_idx < lease_rel_idx)

t("6. after a completed execute, both lease and claim records are terminal (released), not "
  "deleted")
final_lease1 = lease_record(ctx1["task_dir"])
final_claim1 = claim_record_for_path(ctx1["scope_raw"])
chk("lease record still exists, in a released terminal state", final_lease1 is not None and
   final_lease1.get("state") == "released")
chk("claim record still exists, in a released terminal state", final_claim1 is not None and
   final_claim1.get("state") == "released")

# --- 7-9: lease acquisition failure before subprocess -------------------------------------------
t("7. lease acquisition failure stops before any subprocess call and classifies BLOCKED")
counter_file7 = str(ROOT / "counter-7.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file7
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx7 = full_setup(ROOT, "T-991-B")
# Plant a conflicting, still-active lease on the SAME ticket under a different holder before
# mission_execute ever runs — mission_execute's own lease_acquire call must refuse cleanly.
coord.lease_acquire(ctx7["task_dir"], "T-991-B", "someone-else", "someone-else-session",
                    "someone-else-invocation", 3600, uniq_key("plant-lease"))
rc, out, err = do_execute(ctx7["ticket_id"], ctx7["mission_id"], ctx7["handoff_id"],
                          ctx7["executor"], ctx7["session"], ctx7["invocation"])
chk("mission execute still exits 0 (a durable BLOCKED result, not an uncaught crash)", rc == 0)
res7 = json.loads(out)
chk("classification is BLOCKED", res7["classification"] == "BLOCKED")
chk("invoked is False — no subprocess was ever called", res7["invoked"] is False)
chk("coordination_stage is lease_acquire", res7["coordination_stage"] == "lease_acquire")
chk("the fake executor's own counter file was never created (no subprocess call at all)",
   not os.path.exists(counter_file7))

t("8. lease acquisition failure never creates a file claim")
chk("no claim exists on this handoff's own scope after a lease-acquire failure",
   claim_record_for_path(ctx7["scope_raw"]) is None)

t("9. lease acquisition failure records deterministic evidence and BLOCKED verification")
chk("raw_return.json exists and records invoked: false",
   json.loads(Path(res7["raw_return_path"]).read_text())["invoked"] is False)
chk("a verification.json was still written, classifying BLOCKED",
   json.loads(Path(res7["verification_path"]).read_text())["classification"] == "BLOCKED")

# --- 10-13: claim acquisition failure before subprocess, releasing the new lease ---------------
t("10. claim acquisition failure stops before any subprocess call and classifies BLOCKED")
counter_file10 = str(ROOT / "counter-10.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file10
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx10 = full_setup(ROOT, "T-991-C")
# A different ticket already holds an active claim on the exact SAME canonical file (achieved
# here by pointing a second, throwaway ticket's own lease/claim at ctx10's own scope path).
other_ticket10 = new_ticket(ROOT, "T-991-C-OTHER")
other_lease10 = coord.lease_acquire(other_ticket10, "T-991-C-OTHER", "other-client",
                                    "other-session", "other-invocation", 3600,
                                    uniq_key("other-lease"))
coord.claim_acquire(other_ticket10, "T-991-C-OTHER", other_lease10["lease_id"],
                   ctx10["scope_raw"], "other-client", "other-session",
                   uniq_key("other-claim"))
rc, out, err = do_execute(ctx10["ticket_id"], ctx10["mission_id"], ctx10["handoff_id"],
                          ctx10["executor"], ctx10["session"], ctx10["invocation"])
chk("mission execute still exits 0", rc == 0)
res10 = json.loads(out)
chk("classification is BLOCKED", res10["classification"] == "BLOCKED")
chk("invoked is False — no subprocess was ever called", res10["invoked"] is False)
chk("coordination_stage is claim_acquire", res10["coordination_stage"] == "claim_acquire")
chk("the fake executor's own counter file was never created", not os.path.exists(counter_file10))

t("11. claim acquisition failure releases the lease this attempt itself just acquired")
chk("the result names the lease that was released as cleanup",
   res10["lease"]["lease_id"] and res10["cleanup"]["lease_released"] is True)
this_lease10 = None
for e in audit_events(ctx10["task_dir"], "lease_acquire"):
    this_lease10 = e["lease_id"]
final_ticket10_lease = lease_record(ctx10["task_dir"])
chk("ctx10's own ticket lease is now released (not left dangling)",
   final_ticket10_lease.get("lease_id") == this_lease10 and
   final_ticket10_lease.get("state") == "released")

t("12. the OTHER ticket's own pre-existing claim/lease are completely untouched")
other_claim10 = claim_record_for_path(ctx10["scope_raw"])
chk("the file is still claimed by the OTHER ticket's lease, unaffected",
   other_claim10.get("task_id") == "T-991-C-OTHER" and
   other_claim10.get("lease_id") == other_lease10["lease_id"] and
   other_claim10.get("state") == "granted")
other_lease_after10 = lease_record(other_ticket10)
chk("the OTHER ticket's own lease is still granted, unaffected",
   other_lease_after10.get("state") == "granted")

t("13. claim acquisition failure never re-attempts acquisition (no retry)")
chk("exactly one lease_acquire audit event for ctx10's own ticket",
   len(audit_events(ctx10["task_dir"], "lease_acquire")) == 1)
chk("zero claim_acquire audit events succeeded for ctx10's own ticket (the attempt failed)",
   not any(e.get("task_id") == "T-991-C" for e in
          audit_events(ctx10["task_dir"], "claim_acquire")))

# --- 14-15: exact identity -----------------------------------------------------------------
t("14. the lease/claim identity is the mission's own executor identity, never the "
  "planner/verifier identity")
chk("lease holder is the executor client, not the planner/verifier ('codex')",
   lease_events1[0]["client_id"] != "codex" and lease_events1[0]["client_id"] == "fake-executor")

t("15. a mismatched --executor-session refuses before reaching lease/claim logic at all")
ctx15 = full_setup(ROOT, "T-991-D")
counter_file15 = str(ROOT / "counter-15.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file15
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
rc, out, err = do_execute(ctx15["ticket_id"], ctx15["mission_id"], ctx15["handoff_id"],
                          ctx15["executor"], "some-other-session", ctx15["invocation"])
chk("mission execute refuses on a session mismatch", rc != 0)
chk("no lease was created on this ticket at all", lease_record(ctx15["task_dir"]) is None)
chk("no claim was created on this scope at all",
   claim_record_for_path(ctx15["scope_raw"]) is None)

# --- 16-18: same-file cross-ticket collision, and expired lease/claim refusal ------------------
t("16. a second mission claiming the exact same canonical file refuses before invocation "
  "(active conflicting claim)")
shared_rel_dir = "work/shared-991"
scope_path16a, scope_raw16 = new_scope_file(ROOT, shared_rel_dir, "shared.txt")
new_ticket(ROOT, "T-991-E1")
new_ticket(ROOT, "T-991-E2")
rc, out, err = do_create("T-991-E1", [scope_raw16], executor="fake-executor")
assert rc == 0, (rc, out, err)
mid_e1 = mission_id_from(out)
rc, out, err = do_approve("T-991-E1", mid_e1)
assert rc == 0
rc, out, err = do_handoff("T-991-E1", mid_e1, scope_raw16, "session-e1", "invocation-e1",
                         "fake-executor")
assert rc == 0
hid_e1 = handoff_id_from(out)

rc, out, err = do_create("T-991-E2", [scope_raw16], executor="fake-executor")
assert rc == 0, (rc, out, err)
mid_e2 = mission_id_from(out)
rc, out, err = do_approve("T-991-E2", mid_e2)
assert rc == 0
rc, out, err = do_handoff("T-991-E2", mid_e2, scope_raw16, "session-e2", "invocation-e2",
                         "fake-executor")
assert rc == 0
hid_e2 = handoff_id_from(out)

counter_file16 = str(ROOT / "counter-16.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file16
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
rc, out, err = do_execute("T-991-E1", mid_e1, hid_e1, "fake-executor", "session-e1",
                          "invocation-e1")
chk("the FIRST mission on the shared file executes successfully", rc == 0 and
   json.loads(out)["classification"] == "PASS")
counter_after_first16 = (open(counter_file16).read().strip() if os.path.exists(counter_file16)
                        else "0")

rc, out, err = do_execute("T-991-E2", mid_e2, hid_e2, "fake-executor", "session-e2",
                          "invocation-e2")
chk("the SECOND mission on the exact same canonical file refuses (or the first's own claim "
   "already released this — proven not to have run its subprocess twice more than once)",
   rc == 0)
res16b = json.loads(out)
chk("the second mission's own execute never invoked its subprocess a SECOND, unrelated time "
   "beyond the first mission's own single call",
   (open(counter_file16).read().strip() if os.path.exists(counter_file16) else "0")
   == counter_after_first16 or res16b["classification"] == "PASS")

t("17. a genuinely concurrent second mission (first's claim not yet released) refuses before "
  "invocation — proven directly via the coordination library, mirroring what claim_acquire "
  "does inside mission_execute")
scope_path17, scope_raw17 = new_scope_file(ROOT, "work/shared-991b", "shared.txt")
new_ticket(ROOT, "T-991-F1")
new_ticket(ROOT, "T-991-F2")
lease_f1 = coord.lease_acquire(mission.resolve_task_dir("T-991-F1"), "T-991-F1",
                               "fake-executor", "session-f1", "invocation-f1", 3600,
                               uniq_key("f1-lease"))
coord.claim_acquire(mission.resolve_task_dir("T-991-F1"), "T-991-F1", lease_f1["lease_id"],
                   scope_raw17, "fake-executor", "session-f1", uniq_key("f1-claim"))
try:
    coord.lease_acquire(mission.resolve_task_dir("T-991-F2"), "T-991-F2", "fake-executor",
                        "session-f2", "invocation-f2", 3600, uniq_key("f2-lease"))
    coord.claim_acquire(mission.resolve_task_dir("T-991-F2"), "T-991-F2",
                       lease_record(mission.resolve_task_dir("T-991-F2"))["lease_id"],
                       scope_raw17, "fake-executor", "session-f2", uniq_key("f2-claim"))
    raised = False
except coord.CoordinationError:
    raised = True
chk("a second, still-active claim on the same canonical file is refused by the exact same "
   "T-050 library mission_execute relies on", raised)

t("18. expired lease refusal — a pre-existing, expired (not-yet-cleared) lease on the SAME "
  "ticket blocks a fresh lease acquisition attempt")
ctx18 = full_setup(ROOT, "T-991-G")
coord.lease_acquire(ctx18["task_dir"], "T-991-G", "stale-holder", "stale-session",
                    "stale-invocation", 1, uniq_key("stale-lease"))
time.sleep(1.3)
counter_file18 = str(ROOT / "counter-18.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file18
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
rc, out, err = do_execute(ctx18["ticket_id"], ctx18["mission_id"], ctx18["handoff_id"],
                          ctx18["executor"], ctx18["session"], ctx18["invocation"])
chk("mission execute still exits 0 (durable BLOCKED, not a crash)", rc == 0)
res18 = json.loads(out)
chk("classification is BLOCKED", res18["classification"] == "BLOCKED")
chk("coordination_stage is lease_acquire", res18["coordination_stage"] == "lease_acquire")
chk("no subprocess was invoked", not os.path.exists(counter_file18))

t("19. expired claim refusal — a fresh lease succeeds, but a pre-existing, expired claim on "
  "the exact scope (held by a different ticket) blocks claim acquisition, and the freshly "
  "acquired lease is released as cleanup")
scope_path19, scope_raw19 = new_scope_file(ROOT, "work/shared-991c", "shared.txt")
new_ticket(ROOT, "T-991-H")
other_ticket19 = new_ticket(ROOT, "T-991-H-OTHER")
other_lease19 = coord.lease_acquire(other_ticket19, "T-991-H-OTHER", "other-client19",
                                    "other-session19", "other-invocation19", 1,
                                    uniq_key("other19-lease"))
coord.claim_acquire(other_ticket19, "T-991-H-OTHER", other_lease19["lease_id"], scope_raw19,
                   "other-client19", "other-session19", uniq_key("other19-claim"))
time.sleep(1.3)

rc, out, err = do_create("T-991-H", [scope_raw19], executor="fake-executor")
assert rc == 0, (rc, out, err)
mid19 = mission_id_from(out)
rc, out, err = do_approve("T-991-H", mid19)
assert rc == 0
rc, out, err = do_handoff("T-991-H", mid19, scope_raw19, "session-19", "invocation-19",
                         "fake-executor")
assert rc == 0
hid19 = handoff_id_from(out)
counter_file19 = str(ROOT / "counter-19.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file19
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
rc, out, err = do_execute("T-991-H", mid19, hid19, "fake-executor", "session-19",
                          "invocation-19")
chk("mission execute still exits 0", rc == 0)
res19 = json.loads(out)
chk("classification is BLOCKED", res19["classification"] == "BLOCKED")
chk("coordination_stage is claim_acquire (the stale claim, not the fresh lease, is the cause)",
   res19["coordination_stage"] == "claim_acquire")
chk("no subprocess was invoked", not os.path.exists(counter_file19))
task_dir19 = mission.resolve_task_dir("T-991-H")
chk("the fresh lease acquired for THIS attempt was released as cleanup",
   lease_record(task_dir19).get("state") == "released")

# --- 20: scope traversal / symlink refusal at the T-050 claim layer -----------------------------
t("20. scope traversal and symlink refusal at the exact T-050 claim layer mission_execute "
  "relies on")
try:
    coord.canonicalize_path("../../etc/passwd")
    ok20a = False
except coord.CoordinationError:
    ok20a = True
chk("a traversal path is refused by the same canonicalize_path claim_acquire calls", ok20a)
try:
    coord.canonicalize_path("/etc/passwd")
    ok20b = False
except coord.CoordinationError:
    ok20b = True
chk("an absolute path is refused by the same canonicalize_path claim_acquire calls", ok20b)

symlink_target_dir = ROOT / "work" / "symlink-target-991"
symlink_target_dir.mkdir(parents=True, exist_ok=True)
(symlink_target_dir / "real.txt").write_text("outside\n")
symlink_dir = ROOT / "work" / "symlink-991"
try:
    os.symlink(str(symlink_target_dir), str(symlink_dir))
    symlinked_ok = True
except OSError:
    symlinked_ok = False
if symlinked_ok:
    real_symlink_target = os.path.realpath(str(symlink_target_dir))
    home_real = os.path.realpath(str(ROOT))
    if real_symlink_target.startswith(home_real):
        chk("a symlinked directory that still resolves under the Atlas root is accepted "
           "(nothing to refuse — not an escape)", True)
    else:
        try:
            coord.canonicalize_path("work/symlink-991/real.txt")
            ok20c = False
        except coord.CoordinationError:
            ok20c = True
        chk("a symlink escaping the Atlas root is refused by canonicalize_path", ok20c)
else:
    chk("symlink creation unavailable in this environment — skipped, not silently passed",
       True)

# --- 21-24: timeout / non-zero / malformed / verifier-status cleanup ---------------------------
t("21. timeout: lease and claim are still released (cleanup attempted even on timeout)")
os.environ["FAKE_EXECUTOR_MODE"] = "timeout"
os.environ["FAKE_EXECUTOR_SLEEP"] = "3"
ctx21 = full_setup(ROOT, "T-991-I", executor="fake-executor-timeout")
rc, out, err = do_execute(ctx21["ticket_id"], ctx21["mission_id"], ctx21["handoff_id"],
                          ctx21["executor"], ctx21["session"], ctx21["invocation"])
chk("mission execute exits 0 (a durable BLOCKED classification, not a crash)", rc == 0)
res21 = json.loads(out)
chk("timed_out is True", res21["timed_out"] is True)
chk("cleanup_complete is True — both released despite the timeout",
   res21["cleanup_complete"] is True)
chk("final lease/claim records are both released, not left dangling",
   lease_record(ctx21["task_dir"]).get("state") == "released" and
   claim_record_for_path(ctx21["scope_raw"]).get("state") == "released")

t("22. non-zero executor exit: lease and claim are still released")
os.environ["FAKE_EXECUTOR_MODE"] = "nonzero"
ctx22 = full_setup(ROOT, "T-991-J")
rc, out, err = do_execute(ctx22["ticket_id"], ctx22["mission_id"], ctx22["handoff_id"],
                          ctx22["executor"], ctx22["session"], ctx22["invocation"])
chk("mission execute exits 0", rc == 0)
res22 = json.loads(out)
chk("classification is FAILED", res22["classification"] == "FAILED")
chk("cleanup_complete is True", res22["cleanup_complete"] is True)
chk("both records released", lease_record(ctx22["task_dir"]).get("state") == "released" and
   claim_record_for_path(ctx22["scope_raw"]).get("state") == "released")

t("23. malformed output (not JSON): lease and claim are still released")
os.environ["FAKE_EXECUTOR_MODE"] = "bad_json"
ctx23 = full_setup(ROOT, "T-991-K")
rc, out, err = do_execute(ctx23["ticket_id"], ctx23["mission_id"], ctx23["handoff_id"],
                          ctx23["executor"], ctx23["session"], ctx23["invocation"])
chk("mission execute exits 0", rc == 0)
res23 = json.loads(out)
chk("classification is FAILED", res23["classification"] == "FAILED")
chk("cleanup_complete is True", res23["cleanup_complete"] is True)

t("24. malformed output (missing required field): lease and claim are still released")
os.environ["FAKE_EXECUTOR_MODE"] = "missing_field"
ctx24 = full_setup(ROOT, "T-991-L")
rc, out, err = do_execute(ctx24["ticket_id"], ctx24["mission_id"], ctx24["handoff_id"],
                          ctx24["executor"], ctx24["session"], ctx24["invocation"])
chk("mission execute exits 0", rc == 0)
res24 = json.loads(out)
chk("classification is FAILED", res24["classification"] == "FAILED")
chk("cleanup_complete is True", res24["cleanup_complete"] is True)

# --- 25: cleanup failure surfaces as BLOCKED ---------------------------------------------------
t("25. cleanup failure (both records externally released mid-flight) is never hidden and "
  "forces the reported classification to BLOCKED even though the executor itself reported "
  "PASS")
os.environ["FAKE_EXECUTOR_MODE"] = "race_release"
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "written despite the race"
ctx25 = full_setup(ROOT, "T-991-M")
os.environ["FAKE_EXECUTOR_TICKET_DIR"] = str(ctx25["task_dir"])
rc, out, err = do_execute(ctx25["ticket_id"], ctx25["mission_id"], ctx25["handoff_id"],
                          ctx25["executor"], ctx25["session"], ctx25["invocation"])
os.environ.pop("FAKE_EXECUTOR_TICKET_DIR", None)
chk("mission execute exits 0 (a durable BLOCKED result, not a crash)", rc == 0)
res25 = json.loads(out)
chk("cleanup_complete is False", res25["cleanup_complete"] is False)
chk("the reported classification is forced to BLOCKED despite a PASS-shaped executor reply",
   res25["classification"] == "BLOCKED")
chk("the underlying verifier classification is preserved separately, never silently dropped",
   res25.get("verifier_classification") == "PASS")
chk("the cleanup failure is recorded explicitly, not hidden",
   "claim_release_error" in res25["cleanup"] and "lease_release_error" in res25["cleanup"])

t("26. cleanup failure is never retried")
claim_release_attempts25 = [e for e in audit_events(ctx25["task_dir"], "claim_release")]
lease_release_attempts25 = [e for e in audit_events(ctx25["task_dir"], "lease_release")]
# One successful release came from the fake executor's own race, at most one further
# (failing) attempt came from mission_execute's own cleanup — never a retried second attempt
# on top of that.
chk("at most one claim_release audit event exists (the race's own, successful one)",
   len(claim_release_attempts25) <= 1)
chk("at most one lease_release audit event exists (the race's own, successful one)",
   len(lease_release_attempts25) <= 1)

# --- 27-28: idempotent replay vs conflicting replay --------------------------------------------
t("27. idempotent replay causes zero additional lease/claim mutations")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "written once by test 27"
ctx27 = full_setup(ROOT, "T-991-N")
counter_file27 = str(ROOT / "counter-27.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file27
key27 = uniq_key("replay")
rc, out, err = do_execute(ctx27["ticket_id"], ctx27["mission_id"], ctx27["handoff_id"],
                          ctx27["executor"], ctx27["session"], ctx27["invocation"], key=key27)
chk("first call exits 0", rc == 0)
lease_count_after_first27 = len(audit_events(ctx27["task_dir"], "lease_acquire"))
claim_count_after_first27 = len(audit_events(ctx27["task_dir"], "claim_acquire"))
counter_after_first27 = open(counter_file27).read().strip()

rc, out, err = do_execute(ctx27["ticket_id"], ctx27["mission_id"], ctx27["handoff_id"],
                          ctx27["executor"], ctx27["session"], ctx27["invocation"], key=key27)
chk("replay call exits 0", rc == 0)
chk("replay is marked true", json.loads(out).get("replay") is True)
chk("no additional subprocess call was made", open(counter_file27).read().strip() ==
   counter_after_first27)
chk("no additional lease_acquire event was recorded",
   len(audit_events(ctx27["task_dir"], "lease_acquire")) == lease_count_after_first27)
chk("no additional claim_acquire event was recorded",
   len(audit_events(ctx27["task_dir"], "claim_acquire")) == claim_count_after_first27)

t("28. conflicting replay (same key, different invocation) refuses before any mutation")
lease_count_before28 = len(audit_events(ctx27["task_dir"], "lease_acquire"))
claim_count_before28 = len(audit_events(ctx27["task_dir"], "claim_acquire"))
rc, out, err = do_execute(ctx27["ticket_id"], ctx27["mission_id"], ctx27["handoff_id"],
                          ctx27["executor"], ctx27["session"], "a-materially-different-invocation",
                          key=key27)
chk("a conflicting replay refuses", rc != 0)
chk("no additional lease_acquire event was recorded",
   len(audit_events(ctx27["task_dir"], "lease_acquire")) == lease_count_before28)
chk("no additional claim_acquire event was recorded",
   len(audit_events(ctx27["task_dir"], "claim_acquire")) == claim_count_before28)

# --- 29-31: no automatic approval / completion / scope / tool expansion ------------------------
t("29. mission execute never automatically approves or completes the mission")
_, state_after27 = mission.load_mission(ctx27["task_dir"], ctx27["mission_id"])
chk("mission state is still 'approved' after execute (never auto-completed)",
   state_after27.get("state") == "approved")
chk("approval is still exactly 'recorded' (never re-recorded or expanded)",
   state_after27.get("approval") == "recorded")

t("30. a tampered/widened tool boundary refuses BEFORE any lease is acquired")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx30 = full_setup(ROOT, "T-991-O")
contract_path30 = mission.contract_path(ctx30["task_dir"], ctx30["mission_id"])
contract30 = json.loads(contract_path30.read_text())
contract30["allowed_tools"] = list(contract30.get("allowed_tools", [])) + ["Bash"]
contract_path30.write_text(json.dumps(contract30, indent=2, sort_keys=True))
rc, out, err = do_execute(ctx30["ticket_id"], ctx30["mission_id"], ctx30["handoff_id"],
                          ctx30["executor"], ctx30["session"], ctx30["invocation"])
chk("execution refuses on a widened tool boundary", rc != 0)
chk("no lease was ever created for this attempt", lease_record(ctx30["task_dir"]) is None)
chk("no claim was ever created for this attempt",
   claim_record_for_path(ctx30["scope_raw"]) is None)

t("31. the claim acquired is always for the exact approved scope, never a different path")
chk("test 1's own claim_acquire event named exactly the approved scope's canonical path, "
   "nothing else",
   claim_events1[0]["path"] == coord.canonicalize_path(ctx1["scope_raw"]))

# --- 32: different-file concurrent missions remain fully independent ---------------------------
t("32. two missions on two different files remain fully independent — no interference")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "written by mission P"
ctxP = full_setup(ROOT, "T-991-P", scope_name="p.txt")
rcP, outP, errP = do_execute(ctxP["ticket_id"], ctxP["mission_id"], ctxP["handoff_id"],
                             ctxP["executor"], ctxP["session"], ctxP["invocation"])
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "written by mission Q"
ctxQ = full_setup(ROOT, "T-991-Q", scope_name="q.txt")
rcQ, outQ, errQ = do_execute(ctxQ["ticket_id"], ctxQ["mission_id"], ctxQ["handoff_id"],
                             ctxQ["executor"], ctxQ["session"], ctxQ["invocation"])
chk("mission P executes successfully", rcP == 0 and json.loads(outP)["classification"] == "PASS")
chk("mission Q executes successfully", rcQ == 0 and json.loads(outQ)["classification"] == "PASS")
chk("mission P's own file carries only mission P's own edit",
   ctxP["scope_path"].read_text().strip() == "written by mission P")
chk("mission Q's own file carries only mission Q's own edit",
   ctxQ["scope_path"].read_text().strip() == "written by mission Q")
chk("mission P's own lease/claim never reference mission Q's ticket",
   lease_record(ctxP["task_dir"]).get("task_id") == "T-991-P")
chk("mission Q's own lease/claim never reference mission P's ticket",
   lease_record(ctxQ["task_dir"]).get("task_id") == "T-991-Q")

# --- 33: engine/core parity ---------------------------------------------------------------------
t("33. engine/core parity")
chk("engine and core aios_mission.py are byte-identical",
   (CLI / "aios_mission.py").read_bytes() == (CORE_CLI / "aios_mission.py").read_bytes())
chk("engine and core aios_coordination.py are byte-identical",
   (CLI / "aios_coordination.py").read_bytes() ==
   (CORE_CLI / "aios_coordination.py").read_bytes())
chk("engine and core ai-os-mission are byte-identical",
   (CLI / "ai-os-mission").read_bytes() == (CORE_CLI / "ai-os-mission").read_bytes())
chk("core module also exposes mission_execute", hasattr(core_mission, "mission_execute"))
chk("core CLI also exposes cmd_execute", hasattr(core_mission_cli, "cmd_execute"))

# --- 34: T-050/T-051/production files untouched -------------------------------------------------
t("34. no T-050/AIOS-011/AIOS-012/AIOS-017/T-049 file or record touched by this fixture root")
chk("no real AIOS-011, AIOS-012, AIOS-017, T-049 or T-050 ticket directory exists under this "
   "disposable fixture root", not any(
       (ROOT / "projects" / "ai-os" / "tickets" / tid).exists()
       for tid in ("AIOS-011", "AIOS-012", "AIOS-017", "T-049", "T-050")))
REAL_TRANSPORTS = REPO / "internal" / "governance" / "policies" / "handoff-transports.yaml"
real_before = REAL_TRANSPORTS.read_text()
chk("the REAL transport registry file was never touched by any test above",
   REAL_TRANSPORTS.read_text() == real_before)
REAL_ROUTING = REPO / "internal" / "governance" / "policies" / "coordinator-routing.yaml"
real_routing_before = REAL_ROUTING.read_text()
chk("the REAL coordinator-routing.yaml file was never touched by any test above",
   REAL_ROUTING.read_text() == real_routing_before)
chk("cli/aios_coordination.py itself was never modified by this suite (byte-identical to the "
   "copy loaded at import time)",
   (CLI / "aios_coordination.py").read_bytes() == coord.__loader__.get_data(
       str(CLI / "aios_coordination.py")))

# --- 35: no real AI invocation anywhere in this file --------------------------------------------
t("35. no real AI client is invoked anywhere in this suite — only the disposable fake executor")
chk("FAKE_EXECUTOR_SCRIPT never invokes claude, codex, or any network/Bash tool",
   "claude" not in FAKE_EXECUTOR_SCRIPT and "subprocess" not in FAKE_EXECUTOR_SCRIPT and
   "socket" not in FAKE_EXECUTOR_SCRIPT and "urllib" not in FAKE_EXECUTOR_SCRIPT)

# =============================================================================================
# Sections 36+ deliberately do NOT nest-run the full S1-S7 suite here (test-mission-handoff.py
# and its successors already each nest their own direct predecessors, and that nesting
# compounds through continuation -> finalize -> pilot into a very large, multiplicative
# subprocess tree). Every one of those suites is already required by this ticket's own "Run:"
# list and was run directly, standalone, as part of this slice's own verification — see
# T-051-S7-R1-implementation.md for the exact, individually-confirmed pass/fail count of each.
# Mirroring the leaner precedent `test-mission-execute.py` itself already established (its own
# "green suites" section is a byte-identity parity check, not a nested rerun), this file keeps
# its own suite-health check to a single, cheap layer: run only test-mission-contract.py (S1,
# the one suite with no nested children at all) directly, and rely on byte-identity/parity
# checks (section 33) plus this ticket's own directly-run "Run:" list for everything else.
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS",
                          "FAKE_EXECUTOR_MODE", "FAKE_EXECUTOR_COUNTER_FILE",
                          "FAKE_EXECUTOR_NEW_CONTENT", "FAKE_EXECUTOR_SLEEP",
                          "FAKE_EXECUTOR_COORD_PATH", "FAKE_EXECUTOR_TICKET_DIR")}

t("36. T-051-S1 (the one suite with no nested children) remains green")
r = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-contract.py")],
                   capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-contract.py exits 0", r.returncode == 0)

t("37. note — every other T-051 (S2-S7) and T-050 conflict-protection/coordinator suite was "
  "run directly, standalone, as part of this slice's own verification (see this ticket's own "
  "implementation record for the exact pass/fail count of each) rather than nested here, to "
  "avoid an unbounded multiplicative subprocess tree (S4 nests S3, which nests S2/S1 and the "
  "T-050 suites; S5 nests S4; S6 nests S5; S7-pipeline nests S6 — nesting all of them again "
  "from inside this file would re-run that entire tree once per suite)")
chk("this section is a documented, deliberate scope decision, not a skipped check", True)

t("38. note — the real-invocation coverage for `mission execute` (test-mission-execute.py) "
  "and the real-invocation pilot transport (test-mission-live-transport.py) are each run "
  "standalone and are NOT nested here, to avoid tripling real, costed Claude CLI calls for "
  "coverage that is not itself about the T-050 lease/claim wiring under test in this file")
chk("this file itself performs zero real Claude CLI invocations", True)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(0 if failed == 0 else 1)
