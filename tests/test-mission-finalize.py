#!/usr/bin/env python3
"""tests/test-mission-finalize.py — T-051-S6: the completion, failure, and notification
packet (`mission finalize`) on top of the T-051-S1 contract, T-051-S2 role resolution,
T-051-S3 bounded handoff, T-051-S4 verifier gate, and T-051-S5 continuation loop.

Every scenario runs against a disposable ATLAS_HOME, plus a disposable adapter registry and
a disposable transport registry (via ATLAS_ADAPTERS / ATLAS_HANDOFF_TRANSPORTS), exactly like
every prior T-051 mission test file's own fixture pattern. Nothing here reads or writes the
real `adapters/`, the real `internal/governance/policies/handoff-transports.yaml`, any real
T-050 record, or any real mission record.

This file proves the S6 scope only: `mission finalize` reads one existing handoff's own S4
verification `classification` field — never a raw executor status — and, once every mission
limit and every piece of evidence checks out (including a self-contradiction check), writes
exactly one set of durable final packets under the mission's own directory and moves the
mission into exactly one terminal state. No planner, executor, or verifier is ever invoked.
No lease, claim, or V6 handoff record is ever created. No new handoff is ever created. Owner
approval evidence is never rewritten. A mission is finalized at most once.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
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
    modname = f"under_test_{cli_dir.parent.name}_{name.replace('-', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_loader(
        modname, importlib.machinery.SourceFileLoader(modname, str(cli_dir / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mission_cli = _load(CLI, "atlas-mission")
mission = _load(CLI, "atlas_mission.py")
core_mission_cli = _load(CORE_CLI, "atlas-mission")
core_mission = _load(CORE_CLI, "atlas_mission.py")


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


# =============================================================================================
# Fixture registries — same pattern as every prior T-051 mission test file.
# =============================================================================================

ADAPTER_YAML = """\
adapter: {client}
name: fixture adapter for {client}
contract: 1

client:
  detect: [/nonexistent]
  version_cmd: {client}-bin --version
  consumer_verified: false

provides:
  rules: { path: /nonexistent, format: markdown, verified: true }

writes: []
requires: []
enforces: []
"""


def write_adapter(adapters_dir, client):
    d = adapters_dir / client
    d.mkdir(parents=True, exist_ok=True)
    (d / "adapter.yaml").write_text(ADAPTER_YAML.replace("{client}", client))


TRANSPORT_ENTRY = """\
  {client}:
    name: fixture transport for {client}
    binary: {client}-bin
    argv: [--tools, "Read,Edit"]
    stdin: packet
    timeout: 60
    verified: true
    evidence: fixture, not a real trial
"""


def write_transports(path, clients):
    body = "contract: 1\n\ntransports:\n"
    for c in clients:
        body += TRANSPORT_ENTRY.format(client=c)
    path.write_text(body)


def new_fixture(ticket_id="T-950"):
    tmp = Path(tempfile.mkdtemp(prefix="t051-s6-"))
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-finalize tests\nstate: active\n"
        "project: demo\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id))

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    transports_path = tmp / "handoff-transports.yaml"

    for c in ("test-planner", "test-executor", "test-verifier"):
        write_adapter(adapters_dir, c)
    write_transports(transports_path, ["test-planner", "test-executor", "test-verifier"])

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["ATLAS_ADAPTERS"] = str(adapters_dir)
    os.environ["ATLAS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp, d, adapters_dir, transports_path


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def do_create(task_id, scopes=("scope-a.txt",), budget="5", max_slices="3",
             max_attempts="5", ttl="3600", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("create")
    args = [task_id]
    for s in scopes:
        args += ["--scope", s]
    args += ["--planner", "test-planner", "--executor", "test-executor", "--verifier",
            "test-verifier", "--budget-usd", budget, "--max-slices", max_slices,
            "--max-attempts", max_attempts, "--ttl-seconds", ttl, "--idempotency-key", key]
    return run(m.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def do_approve(task_id, mission_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("approve")
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words", "approved by fixture",
                               "--idempotency-key", key])


def do_handoff(task_id, mission_id, scope="scope-a.txt", executor_client="test-executor",
              session="sess-fixed", invocation="inv-fixed", gate="execute", budget="1",
              key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("handoff")
    args = [task_id, mission_id, "--scope", scope, "--executor-client", executor_client,
           "--executor-session", session, "--invocation-id", invocation, "--gate", gate,
           "--slice-budget-usd", budget, "--idempotency-key", key, "--json"]
    return run(m.cmd_handoff, args)


def make_handoff(task_id="T-950", m=None, create_kwargs=None, handoff_kwargs=None):
    m = m or mission_cli
    create_kwargs = create_kwargs or {}
    handoff_kwargs = handoff_kwargs or {}
    rc, out, err = do_create(task_id, m=m, **create_kwargs)
    assert rc == 0, (rc, out, err)
    mid = mission_id_from(out)
    rc, out, err = do_approve(task_id, mid, m=m)
    assert rc == 0, (rc, out, err)
    rc, out, err = do_handoff(task_id, mid, m=m, **handoff_kwargs)
    assert rc == 0, (rc, out, err)
    hid = json.loads(out)["handoff_id"]
    return mid, hid


def result_hash(handoff_id, mission_id, root_task_id="T-950", status="pass",
                changed_files=("scope-a.txt",), tests_field=("pytest ok",),
                summary="did the thing"):
    material = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "status": status, "changed_files": sorted(changed_files), "tests": tests_field,
        "summary": summary,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def make_result(handoff_id, mission_id, root_task_id="T-950",
                executor_client="test-executor", executor_session="sess-fixed",
                invocation_id="inv-fixed", gate="execute", scope="scope-a.txt",
                status="pass", changed_files=("scope-a.txt",), tests=("pytest ok",),
                reported_cost_usd=0.5, summary="did the thing", blocker=None,
                owner_decision_required=None, bad_hash=False, tests_list=True):
    tests_field = list(tests) if tests_list else (tests[0] if tests else "")
    h = result_hash(handoff_id, mission_id, root_task_id, status, changed_files, tests_field,
                    summary)
    if bad_hash:
        h = "0" * 64
    result = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "executor_client": executor_client, "executor_session": executor_session,
        "invocation_id": invocation_id, "gate": gate, "scope": scope, "status": status,
        "changed_files": list(changed_files), "tests": tests_field,
        "result_sha256": h, "reported_cost_usd": reported_cost_usd, "summary": summary,
    }
    if blocker is not None:
        result["blocker"] = blocker
    if owner_decision_required is not None:
        result["owner_decision_required"] = owner_decision_required
    return result


def write_result_file(tmp_root, result_obj, name=None):
    name = name or uniq_key("result") + ".json"
    p = Path(tmp_root) / name
    p.write_text(json.dumps(result_obj))
    return str(p)


def do_verify(task_id, mission_id, handoff_id, result_file, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("verify")
    return run(m.cmd_verify, [task_id, mission_id, handoff_id, "--result-file", result_file,
                             "--idempotency-key", key, "--json"])


def make_verified_handoff(task_id="T-950", root=None, d=None, status="pass", m=None,
                          create_kwargs=None, handoff_kwargs=None, result_kwargs=None):
    m = m or mission_cli
    result_kwargs = result_kwargs or {}
    mid, hid = make_handoff(task_id, m=m, create_kwargs=create_kwargs,
                            handoff_kwargs=handoff_kwargs)
    res = make_result(hid, mid, root_task_id=task_id, status=status, **result_kwargs)
    rf = write_result_file(root, res)
    rc, out, err = do_verify(task_id, mid, hid, rf, m=m)
    assert rc == 0, (rc, out, err)
    classification = json.loads(out)["classification"]
    return mid, hid, classification


def do_continue(task_id, mission_id, handoff_id, scope="scope-a.txt",
                executor_client="test-executor", session="sess-fixed",
                invocation="inv-continue", gate="execute", budget="1", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("continue")
    args = [task_id, mission_id, handoff_id, "--scope", scope, "--executor-client",
           executor_client, "--executor-session", session, "--invocation-id", invocation,
           "--gate", gate, "--slice-budget-usd", budget, "--idempotency-key", key, "--json"]
    return run(m.cmd_continue, args)


def do_finalize(task_id, mission_id, handoff_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("finalize")
    return run(m.cmd_finalize, [task_id, mission_id, handoff_id, "--idempotency-key", key,
                               "--json"])


# =============================================================================================
t("1. PASS finalization -> completed")
root, d, adapters_dir, transports_path = new_fixture()
(d / "scope-a.txt").write_text("x")
mid1, hid1, cls1 = make_verified_handoff(root=root, d=d)
rc, out, err = do_finalize("T-950", mid1, hid1)
chk("finalizing a PASS handoff exits 0", rc == 0)
view1 = json.loads(out) if rc == 0 else {}
chk("final_classification is PASS", view1.get("final_classification") == "PASS")
chk("mission_state is completed", view1.get("mission_state") == "completed")
state1 = json.loads(mission.state_path(d, mid1).read_text())
chk("mission state.json now reads state=completed", state1["state"] == "completed")
chk("final-report.json exists", Path(view1["final_report_path"]).is_file())
chk("session-summary.json exists", Path(view1["session_summary_path"]).is_file())
chk("notification-packet.json exists", Path(view1["notification_packet_path"]).is_file())
chk("no blocker-packet.json for a PASS finalize", view1.get("blocker_packet_path") is None)
chk("no owner-decision-packet.json for a PASS finalize",
    view1.get("owner_decision_packet_path") is None)

# =============================================================================================
t("2. BLOCKED finalization -> blocked")
mid2, hid2, cls2 = make_verified_handoff(root=root, d=d, status="blocked",
                                         result_kwargs={"blocker": "dependency missing"})
rc, out, err = do_finalize("T-950", mid2, hid2)
chk("finalizing a BLOCKED handoff exits 0", rc == 0)
view2 = json.loads(out)
chk("final_classification is BLOCKED", view2["final_classification"] == "BLOCKED")
chk("mission_state is blocked", view2["mission_state"] == "blocked")
chk("blocker-packet.json exists for BLOCKED", Path(view2["blocker_packet_path"]).is_file())
chk("no owner-decision-packet.json for BLOCKED", view2.get("owner_decision_packet_path") is None)

# =============================================================================================
t("3. FAILED finalization -> failed")
mid3, hid3, cls3 = make_verified_handoff(root=root, d=d, status="failed")
rc, out, err = do_finalize("T-950", mid3, hid3)
chk("finalizing a FAILED handoff exits 0", rc == 0)
view3 = json.loads(out)
chk("final_classification is FAILED", view3["final_classification"] == "FAILED")
chk("mission_state is failed", view3["mission_state"] == "failed")
chk("blocker-packet.json exists for FAILED", Path(view3["blocker_packet_path"]).is_file())

# =============================================================================================
t("4. NEEDS_OWNER finalization -> needs_owner")
mid4, hid4, cls4 = make_verified_handoff(
    root=root, d=d, status="needs_owner",
    result_kwargs={"owner_decision_required": "ambiguous, please decide"})
rc, out, err = do_finalize("T-950", mid4, hid4)
chk("finalizing a NEEDS_OWNER handoff exits 0", rc == 0)
view4 = json.loads(out)
chk("final_classification is NEEDS_OWNER", view4["final_classification"] == "NEEDS_OWNER")
chk("mission_state is needs_owner", view4["mission_state"] == "needs_owner")
chk("owner-decision-packet.json exists for NEEDS_OWNER",
    Path(view4["owner_decision_packet_path"]).is_file())
chk("no blocker-packet.json for NEEDS_OWNER", view4.get("blocker_packet_path") is None)

# =============================================================================================
t("5. missing verification refuses")
mid5, hid5 = make_handoff()
rc, out, err = do_finalize("T-950", mid5, hid5)
chk("finalize against a handoff with no verify call yet refuses",
    rc == 5 and "missing verification evidence" in err)

# =============================================================================================
t("6. contradictory verification refuses")
mid6, hid6, cls6 = make_verified_handoff(root=root, d=d)
vpath6 = mission.verification_path(d, mid6, hid6)
vobj6 = json.loads(vpath6.read_text())
for c in vobj6["checks"]:
    if c["check"] == "within_budget":
        c["ok"] = False
vpath6.write_text(json.dumps(vobj6))
rc, out, err = do_finalize("T-950", mid6, hid6)
chk("a verification record whose checks contradict its own classification refuses",
    rc == 5 and "contradictory" in err)

# =============================================================================================
t("7. unresolved previous handoff refuses")
mid7, hid7, cls7 = make_verified_handoff(
    root=root, d=d, create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt"),
                                   "max_attempts": "5", "max_slices": "5"})
(d / "scope-b.txt").write_text("y")
rc, out, err = do_continue("T-950", mid7, hid7, scope="scope-b.txt")
assert rc == 0, (rc, out, err)
hid7b = json.loads(out)["handoff_id"]
# hid7b was never verified — the mission now has an unresolved handoff.
rc, out, err = do_finalize("T-950", mid7, hid7)
chk("finalize refuses while a sibling handoff on this mission has no verification evidence",
    rc == 5 and "unresolved previous handoff" in err)

# =============================================================================================
t("8. budget limit violation refuses")
mid8, hid8, cls8 = make_verified_handoff(root=root, d=d, create_kwargs={"budget": "1"},
                                         handoff_kwargs={"budget": "1"})
state8 = json.loads(mission.state_path(d, mid8).read_text())
state8["budget_committed_usd"] = 999.0
mission.state_path(d, mid8).write_text(json.dumps(state8))
rc, out, err = do_finalize("T-950", mid8, hid8)
chk("a budget_committed_usd exceeding budget_usd refuses finalize",
    rc == 5 and "budget" in err.lower())

# =============================================================================================
t("9. attempt limit violation refuses")
mid9, hid9, cls9 = make_verified_handoff(root=root, d=d, create_kwargs={"max_attempts": "1"})
state9 = json.loads(mission.state_path(d, mid9).read_text())
state9["attempts_used"] = 999
mission.state_path(d, mid9).write_text(json.dumps(state9))
rc, out, err = do_finalize("T-950", mid9, hid9)
chk("attempts_used exceeding max_attempts refuses finalize",
    rc == 5 and "max_attempts" in err)

# =============================================================================================
t("10. TTL violation refuses")
mid10, hid10, cls10 = make_verified_handoff(root=root, d=d, create_kwargs={"ttl": "1"})
time.sleep(1.2)
rc, out, err = do_finalize("T-950", mid10, hid10)
chk("finalize refuses once ttl_seconds has elapsed since approval",
    rc == 5 and "ttl" in err.lower())

# =============================================================================================
t("11. scope limit violation refuses")
mid11, hid11, cls11 = make_verified_handoff(root=root, d=d)
packet11 = mission.handoff_dir(d, mid11, hid11) / "packet.json"
pobj11 = json.loads(packet11.read_text())
pobj11["scope"] = {"raw": "not-approved.txt", "canonical": str(d / "not-approved.txt")}
packet11.write_text(json.dumps(pobj11))
rc, out, err = do_finalize("T-950", mid11, hid11)
chk("a handoff packet whose scope is no longer one of the mission's approved scopes "
    "refuses finalize", rc == 5)

# =============================================================================================
t("12. identity limit violation refuses")
mid12, hid12, cls12 = make_verified_handoff(root=root, d=d)
packet12 = mission.handoff_dir(d, mid12, hid12) / "packet.json"
pobj12 = json.loads(packet12.read_text())
pobj12["executor_client"] = "test-planner"
packet12.write_text(json.dumps(pobj12))
rc, out, err = do_finalize("T-950", mid12, hid12)
chk("a handoff packet whose executor_client no longer matches the contract refuses finalize",
    rc == 5 and "identity-mismatched" in err)

# =============================================================================================
t("13. finalization idempotency (replay)")
mid13, hid13, cls13 = make_verified_handoff(root=root, d=d)
key13 = uniq_key("idem")
rc1, out1, _ = do_finalize("T-950", mid13, hid13, key=key13)
rc2, out2, _ = do_finalize("T-950", mid13, hid13, key=key13)
chk("a replayed finalize (same key, same request) exits 0 both times", rc1 == 0 and rc2 == 0)
v1, v2 = json.loads(out1), json.loads(out2)
chk("both replays report the same final packets", v1["final_report_path"] == v2["final_report_path"])
chk("the first call reports replay: false, the second reports replay: true",
    v1["replay"] is False and v2["replay"] is True)

# =============================================================================================
t("14. conflicting replay (same key, different handoff/request)")
mid14, hid14, cls14 = make_verified_handoff(
    root=root, d=d, create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt"),
                                   "max_attempts": "5", "max_slices": "5"})
rc, out, err = do_continue("T-950", mid14, hid14, scope="scope-b.txt")
assert rc == 0, (rc, out, err)
hid14b = json.loads(out)["handoff_id"]
res14b = make_result(hid14b, mid14, root_task_id="T-950", scope="scope-b.txt",
                     changed_files=["scope-b.txt"], invocation_id="inv-continue")
rf14b = write_result_file(root, res14b)
rc, out, err = do_verify("T-950", mid14, hid14b, rf14b)
assert rc == 0, (rc, out, err)
key14 = uniq_key("conflict")
rc1, out1, _ = do_finalize("T-950", mid14, hid14, key=key14)
chk("the first finalize call with a fresh key succeeds", rc1 == 0)
rc2, out2, err2 = do_finalize("T-950", mid14, hid14b, key=key14)
chk("reusing the same key for a different handoff refuses as conflicting",
    rc2 == 5 and ("already finalized" in err2 or "conflict" in err2.lower()
                  or "different" in err2.lower()))

# =============================================================================================
t("15. deterministic final packets")
mid15, hid15, cls15 = make_verified_handoff(root=root, d=d)
key15 = uniq_key("det")
do_finalize("T-950", mid15, hid15, key=key15)
rc1, out1, _ = do_finalize("T-950", mid15, hid15, key=key15)
rc2, out2, _ = do_finalize("T-950", mid15, hid15, key=key15)
chk("repeated replay JSON output is byte-identical", rc1 == rc2 == 0 and out1 == out2)
report15a = Path(json.loads(out1)["final_report_path"]).read_text()
report15b = Path(json.loads(out2)["final_report_path"]).read_text()
chk("final-report.json is byte-identical across replays", report15a == report15b)

# =============================================================================================
t("16. notification packet contents")
mid16, hid16, cls16 = make_verified_handoff(root=root, d=d)
rc, out, err = do_finalize("T-950", mid16, hid16)
notif16 = json.loads(Path(json.loads(out)["notification_packet_path"]).read_text())
chk("notification packet carries mission_id", notif16["mission_id"] == mid16)
chk("notification packet carries root_task_id", notif16["root_task_id"] == "T-950")
chk("notification packet carries final_classification", notif16["final_classification"] == "PASS")
chk("notification packet is marked signal-only", notif16["is_signal_only"] is True)
chk("notification packet declares no_automatic_action", notif16["no_automatic_action"] is True)
chk("notification packet declares no_os_notification", notif16["no_os_notification"] is True)
chk("notification packet declares no_webhook", notif16["no_webhook"] is True)
chk("notification packet declares no_network_call", notif16["no_network_call"] is True)

# =============================================================================================
t("17. blocker packet contents")
mid17, hid17, cls17 = make_verified_handoff(root=root, d=d, status="blocked",
                                            result_kwargs={"blocker": "dependency missing"})
rc, out, err = do_finalize("T-950", mid17, hid17)
blocker17 = json.loads(Path(json.loads(out)["blocker_packet_path"]).read_text())
chk("blocker packet carries the blocker text", blocker17["blocker"] == "dependency missing")
chk("blocker packet carries the final handoff id", blocker17["final_handoff_id"] == hid17)
chk("blocker packet carries checks", "checks" in blocker17 and blocker17["checks"])
chk("blocker packet carries an owner_action", bool(blocker17["owner_action"]))
chk("blocker packet carries rollback_policy", bool(blocker17["rollback_policy"]))

# =============================================================================================
t("18. owner decision packet contents")
mid18, hid18, cls18 = make_verified_handoff(
    root=root, d=d, status="needs_owner",
    result_kwargs={"owner_decision_required": "ambiguous, please decide"})
rc, out, err = do_finalize("T-950", mid18, hid18)
owner18 = json.loads(Path(json.loads(out)["owner_decision_packet_path"]).read_text())
chk("owner decision packet carries owner_decision_required",
    owner18["owner_decision_required"] == "ambiguous, please decide")
chk("owner decision packet carries the final handoff id", owner18["final_handoff_id"] == hid18)
chk("owner decision packet carries checks", "checks" in owner18 and owner18["checks"])

# =============================================================================================
t("19. final report contains every required field")
mid19, hid19, cls19 = make_verified_handoff(root=root, d=d)
rc, out, err = do_finalize("T-950", mid19, hid19)
report19 = json.loads(Path(json.loads(out)["final_report_path"]).read_text())
for field in ("mission_id", "root_task_id", "all_handoff_ids",
             "all_verified_classifications", "final_classification", "approved_scope",
             "changed_files", "tests", "reported_cost_usd", "budget_committed_usd",
             "attempts_used", "slices_used", "stop_condition", "rollback_policy",
             "owner_action"):
    chk(f"final report contains {field}", field in report19)
chk("final report's approved_scope matches", report19["approved_scope"] == "scope-a.txt")
chk("final report's changed_files matches the result", report19["changed_files"] == ["scope-a.txt"])

# =============================================================================================
t("20. no duplicate packet")
mid20, hid20, cls20 = make_verified_handoff(root=root, d=d)
key20 = uniq_key("nodupe")
do_finalize("T-950", mid20, hid20, key=key20)
after_first20 = snapshot(root)
do_finalize("T-950", mid20, hid20, key=key20)
after_second20 = snapshot(root)
chk("a replay creates no additional files beyond the first finalize call",
    after_first20 == after_second20)

# =============================================================================================
t("21. no duplicate audit event")
mid21, hid21, cls21 = make_verified_handoff(root=root, d=d)
key21 = uniq_key("noauditdupe")
before21 = mission.audit_path(d, mid21).read_text().count("mission_finalize")
do_finalize("T-950", mid21, hid21, key=key21)
do_finalize("T-950", mid21, hid21, key=key21)
after21 = mission.audit_path(d, mid21).read_text().count("mission_finalize")
chk("only one mission_finalize audit event was appended despite two identical calls",
    after21 == before21 + 1)

# =============================================================================================
t("22. mission finalized at most once — a fresh finalize attempt after completion refuses")
mid22, hid22, cls22 = make_verified_handoff(root=root, d=d)
do_finalize("T-950", mid22, hid22)
rc, out, err = do_finalize("T-950", mid22, hid22, key=uniq_key("second-attempt"))
chk("a second, freshly-keyed finalize attempt on an already-finalized mission refuses",
    rc == 5 and "already finalized" in err)

# =============================================================================================
t("23. owner approval evidence preserved immutably")
mid23, hid23, cls23 = make_verified_handoff(root=root, d=d)
state_before23 = json.loads(mission.state_path(d, mid23).read_text())
do_finalize("T-950", mid23, hid23)
state_after23 = json.loads(mission.state_path(d, mid23).read_text())
chk("approval/owner_words/approval_scope_hash are byte-for-byte unchanged by finalize",
    state_before23["approval"] == state_after23["approval"] and
    state_before23["owner_words"] == state_after23["owner_words"] and
    state_before23["approval_scope_hash"] == state_after23["approval_scope_hash"])

# =============================================================================================
t("24. never approves a new action, never creates a new handoff")
mid24, hid24, cls24 = make_verified_handoff(root=root, d=d)
before_handoffs24 = len(list(mission.handoffs_root(d, mid24).glob("handoff-*")))
do_finalize("T-950", mid24, hid24)
after_handoffs24 = len(list(mission.handoffs_root(d, mid24).glob("handoff-*")))
chk("finalize never creates a new handoff", before_handoffs24 == after_handoffs24 == 1)

# =============================================================================================
t("25. never dispatches, sends, or invokes an AI client")
src = (CLI / "atlas_mission.py").read_text()
s6_section = src[src.index("# T-051-S6 — completion, failure, and notification packet"):]
chk("no subprocess call appears in the S6 section of atlas_mission.py",
    "subprocess.run(" not in s6_section)
chk("no socket/urllib/requests import appears anywhere in atlas_mission.py",
    not any(tok in src for tok in ("import socket", "import urllib", "import requests")))
chk("the only subprocess.run call in the whole file targets atlas-paths (pre-existing, S1)",
    src.count("subprocess.run(") == 1 and "PATHS_RESOLVER" in src)

# =============================================================================================
t("26. never deletes mission evidence")
mid26, hid26, cls26 = make_verified_handoff(root=root, d=d)
packet_before26 = (mission.handoff_dir(d, mid26, hid26) / "packet.json").read_text()
verification_before26 = (mission.handoff_dir(d, mid26, hid26) / "verification.json").read_text()
result_before26 = (mission.handoff_dir(d, mid26, hid26) / "result.json").read_text()
do_finalize("T-950", mid26, hid26)
chk("the handoff's own packet.json is byte-for-byte unchanged",
    (mission.handoff_dir(d, mid26, hid26) / "packet.json").read_text() == packet_before26)
chk("the handoff's own verification.json is byte-for-byte unchanged",
    (mission.handoff_dir(d, mid26, hid26) / "verification.json").read_text() == verification_before26)
chk("the handoff's own result.json is byte-for-byte unchanged",
    (mission.handoff_dir(d, mid26, hid26) / "result.json").read_text() == result_before26)

# =============================================================================================
t("27. no lease, claim, dispatch, send, or V6 handoff record created")
mid27, hid27, cls27 = make_verified_handoff(root=root, d=d)
before27 = snapshot(root)
do_finalize("T-950", mid27, hid27)
after27 = snapshot(root)
new_paths27 = [p for p in after27 if p not in before27]
chk("every new path from a finalize call lives under this mission's own final/ directory "
    "or state/audit files",
    all("/mission/" in p or p.endswith(".lock") for p in new_paths27))
chk("no coordination/ directory exists anywhere under the fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the fixture root",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("28. engine/core parity")
mid_e, hid_e, cls_e = make_verified_handoff(root=root, d=d, m=mission_cli)
mid_c, hid_c, cls_c = make_verified_handoff(root=root, d=d, m=core_mission_cli)
rc_e, out_e, _ = do_finalize("T-950", mid_e, hid_e, m=mission_cli)
rc_c, out_c, _ = do_finalize("T-950", mid_c, hid_c, m=core_mission_cli)
view_e, view_c = json.loads(out_e), json.loads(out_c)
chk("engine and core mission finalize agree on outcome",
    rc_e == 0 and rc_c == 0 and view_e["final_classification"] ==
    view_c["final_classification"] == "PASS")
engine_py = CLI / "atlas_mission.py"
core_py = CORE_CLI / "atlas_mission.py"
chk("engine/cli/atlas_mission.py and core/cli/atlas_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "atlas-mission"
core_cli_file = CORE_CLI / "atlas-mission"
chk("engine/cli/atlas-mission and core/cli/atlas-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())

# =============================================================================================
t("29. protected T-050/T-051 files untouched")
PROTECTED = [
    CLI / "atlas-coordinator", CORE_CLI / "atlas-coordinator",
    CLI / "atlas_coordination.py", CORE_CLI / "atlas_coordination.py",
    CLI / "atlas-handoff", CORE_CLI / "atlas-handoff",
    REPO / "internal" / "governance" / "policies" / "handoff-transports.yaml",
    REPO / "internal" / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())
chk("atlas_mission.py never actually loads atlas-coordinator or atlas_coordination as a module",
    '_load_sibling("atlas-coordinator")' not in src and
    "import atlas_coordination" not in src and "from atlas_coordination" not in src)

# =============================================================================================
t("30. unknown handoff refusal")
mid30, _hid30 = make_handoff()
rc, out, err = do_finalize("T-950", mid30, "handoff-doesnotexist")
chk("finalize against an unknown handoff id refuses", rc == 4 and "handoff" in err)

# =============================================================================================
t("31. closed (already-finalized/blocked) mission refuses a fresh finalize")
mid31, hid31, cls31 = make_verified_handoff(root=root, d=d)
obj31 = json.loads(mission.state_path(d, mid31).read_text())
obj31["state"] = "blocked"
mission.state_path(d, mid31).write_text(json.dumps(obj31))
rc, out, err = do_finalize("T-950", mid31, hid31, key=uniq_key("closed"))
chk("finalize against an already-closed mission refuses", rc == 5 and "already finalized" in err)

# =============================================================================================
t("32. finalize on an unapproved (created-only) mission refuses")
rc, out, err = do_create("T-950")
mid32 = mission_id_from(out)
rc, out, err = do_finalize("T-950", mid32, "handoff-doesnotmatter")
chk("finalize against a never-approved mission refuses",
    rc in (4, 5))

# =============================================================================================
t("33. no --idempotency-key refuses")
mid33, hid33, cls33 = make_verified_handoff(root=root, d=d)
rc, out, err = run(mission_cli.cmd_finalize, ["T-950", mid33, hid33])
chk("a missing --idempotency-key refuses", rc == 2)

# =============================================================================================
t("34. approval scope hash revalidation — stale hash refuses")
mid34, hid34, cls34 = make_verified_handoff(root=root, d=d)
state34 = json.loads(mission.state_path(d, mid34).read_text())
state34["approval_scope_hash"] = "0" * 64
mission.state_path(d, mid34).write_text(json.dumps(state34))
rc, out, err = do_finalize("T-950", mid34, hid34)
chk("a stale/tampered approval_scope_hash refuses finalize",
    rc == 5 and "approval" in err.lower())

# =============================================================================================
t("35. mission show reflects the finalized state")
mid35, hid35, cls35 = make_verified_handoff(root=root, d=d)
do_finalize("T-950", mid35, hid35)
rc, out, err = run(mission_cli.cmd_show, ["T-950", mid35, "--json"])
view35 = json.loads(out)
chk("mission show reports state 'completed' after a PASS finalize",
    view35["state"] == "completed")
chk("mission show's next_owner_action mentions the final report",
    "final-report.json" in view35["next_owner_action"])

# =============================================================================================
t("36. slices_used and attempts_used are accurate in the final report")
mid36, hid36, cls36 = make_verified_handoff(
    root=root, d=d, create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt"),
                                   "max_attempts": "5", "max_slices": "5"})
rc, out, err = do_continue("T-950", mid36, hid36, scope="scope-b.txt")
assert rc == 0, (rc, out, err)
hid36b = json.loads(out)["handoff_id"]
res36b = make_result(hid36b, mid36, root_task_id="T-950", scope="scope-b.txt",
                     changed_files=["scope-b.txt"], invocation_id="inv-continue")
rf36b = write_result_file(root, res36b)
rc, out, err = do_verify("T-950", mid36, hid36b, rf36b)
assert rc == 0, (rc, out, err)
rc, out, err = do_finalize("T-950", mid36, hid36b)
report36 = json.loads(Path(json.loads(out)["final_report_path"]).read_text())
chk("final report's slices_used reflects two distinct scopes", report36["slices_used"] == 2)
chk("final report's attempts_used reflects two attempts", report36["attempts_used"] == 2)
chk("final report's all_handoff_ids lists both handoffs",
    set(report36["all_handoff_ids"]) == {hid36, hid36b})
chk("final report's all_verified_classifications lists both as PASS",
    report36["all_verified_classifications"] == {hid36: "PASS", hid36b: "PASS"})

# =============================================================================================
t("37. session summary contents")
mid37, hid37, cls37 = make_verified_handoff(root=root, d=d)
rc, out, err = do_finalize("T-950", mid37, hid37)
summary37 = json.loads(Path(json.loads(out)["session_summary_path"]).read_text())
for field in ("mission_id", "root_task_id", "final_classification", "mission_state",
             "handoff_count", "attempts_used", "budget_committed_usd", "owner_action",
             "next_owner_action"):
    chk(f"session summary contains {field}", field in summary37)
chk("session summary's handoff_count is 1", summary37["handoff_count"] == 1)

# =============================================================================================
t("38. stop_condition text reflects the classification")
mid38, hid38, cls38 = make_verified_handoff(root=root, d=d, status="blocked",
                                            result_kwargs={"blocker": "network unreachable"})
rc, out, err = do_finalize("T-950", mid38, hid38)
report38 = json.loads(Path(json.loads(out)["final_report_path"]).read_text())
chk("stop_condition mentions BLOCKED", "BLOCKED" in report38["stop_condition"])
chk("stop_condition mentions the blocker text", "network unreachable" in report38["stop_condition"])

# =============================================================================================
t("39. PASS completion conditions must be independently proven, not merely labeled")
mid39, hid39, cls39 = make_verified_handoff(root=root, d=d)
vpath39 = mission.verification_path(d, mid39, hid39)
vobj39 = json.loads(vpath39.read_text())
# Force a self-contradictory record where classification says PASS but a check failed —
# this should be caught by the contradiction check (test 6's own scenario), so instead
# simulate a corrupted classification value directly to hit the "PASS but not proven" path
# without also tripping the earlier contradiction check: mark every check ok EXCEPT one,
# but leave classification PASS (already covered) — here we confirm finalize CANNOT be
# tricked by a persisted PASS whose checks disagree, regardless of which check fails.
for c in vobj39["checks"]:
    if c["check"] == "scope_bounded":
        c["ok"] = False
vpath39.write_text(json.dumps(vobj39))
rc, out, err = do_finalize("T-950", mid39, hid39)
chk("a PASS classification whose own scope_bounded check reads false refuses as "
    "contradictory (never silently completed)", rc == 5 and "contradictory" in err)

# =============================================================================================
t("40. root_task_id mismatch refuses (no automatic ticket selection)")
mid40, hid40, cls40 = make_verified_handoff(root=root, d=d)
task_dir40 = mission.resolve_task_dir("T-950")
rc = None
try:
    mission.mission_finalize(task_dir40, "T-999-WRONG", mid40, hid40, uniq_key("wrongticket"))
except mission.MissionError as e:
    rc = e.code
chk("a mismatched root_task_id refuses rather than silently finalizing under a different "
    "ticket", rc == 4)

# =============================================================================================
t("41. mission validate remains consistent after finalize")
mid41, hid41, cls41 = make_verified_handoff(root=root, d=d)
do_finalize("T-950", mid41, hid41)
rc, out, err = run(mission_cli.cmd_validate, ["T-950", mid41, "--json"])
chk("mission validate does not crash on a finalized mission", rc == 0)

# =============================================================================================
t("42. malformed --handoff-id refuses")
mid42, hid42, cls42 = make_verified_handoff(root=root, d=d)
rc, out, err = run(mission_cli.cmd_finalize,
                   ["T-950", mid42, "not an id!", "--idempotency-key", uniq_key("bad")])
chk("a malformed handoff id refuses", rc == 2)

# =============================================================================================
t("43. every T-051-S1..S5 suite remains green")
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "ATLAS_ADAPTERS", "ATLAS_HANDOFF_TRANSPORTS")}
for name in ("test-mission-contract", "test-mission-routing", "test-mission-handoff",
            "test-mission-result", "test-mission-continuation"):
    r = subprocess.run([sys.executable, str(REPO / "tests" / f"{name}.py")],
                       capture_output=True, text=True, env=_CLEAN_ENV)
    chk(f"{name}.py exits 0", r.returncode == 0)

t("44. all T-050 tests remain green")
for name in ("test-coordinator-conflict-protection", "test-coordinator-routing",
            "test-cli-source-drift"):
    r = subprocess.run([sys.executable, str(REPO / "tests" / f"{name}.py")],
                       capture_output=True, text=True, env=_CLEAN_ENV)
    chk(f"{name}.py exits 0", r.returncode == 0)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(0 if failed == 0 else 1)
