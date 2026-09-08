#!/usr/bin/env python3
"""tests/test-mission-continuation.py — T-051-S5: the safe foreground continuation loop
(`mission continue`) on top of the T-051-S1 contract, T-051-S2 role resolution, T-051-S3
bounded handoff, and T-051-S4 structured result / verifier gate.

Every scenario runs against a disposable ATLAS_HOME, plus a disposable adapter registry and a
disposable transport registry (via ATLAS_ADAPTERS / ATLAS_HANDOFF_TRANSPORTS), exactly like
`test-mission-result.py`'s own fixture pattern. Nothing here reads or writes the real
`adapters/`, the real `governance/policies/handoff-transports.yaml`, any real T-050
record, or any real mission record.

This file proves the S5 scope only: `mission continue` creates at most one next bounded
handoff, only when the referenced handoff's own T-051-S4 verification classified exactly
PASS, and only while every mission limit and contract boundary still holds. No planner,
executor, or verifier is ever invoked. No lease, claim, or V6 handoff record is ever created.
No approval is created or changed. The mission is never advanced toward completed. No
infinite loop, background worker, daemon, or scheduler exists.
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
# Fixture registries — same pattern as test-mission-handoff.py / test-mission-result.py.
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


def new_fixture(ticket_id="T-940"):
    tmp = Path(tempfile.mkdtemp(prefix="t051-s5-"))
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-continuation tests\nstate: active\n"
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


def make_handoff(task_id="T-940", m=None, create_kwargs=None, handoff_kwargs=None):
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


def result_hash(handoff_id, mission_id, root_task_id="T-940", status="pass",
                changed_files=("scope-a.txt",), tests_field=("pytest ok",),
                summary="did the thing"):
    material = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "status": status, "changed_files": sorted(changed_files), "tests": tests_field,
        "summary": summary,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def make_result(handoff_id, mission_id, root_task_id="T-940",
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


def make_verified_handoff(task_id="T-940", root=None, d=None, status="pass", m=None,
                          create_kwargs=None, handoff_kwargs=None, result_kwargs=None):
    """A full create -> approve -> handoff -> verify chain, returning (mid, hid,
    classification)."""
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


# =============================================================================================
t("1. PASS creates exactly one next packet")
root, d, adapters_dir, transports_path = new_fixture()
(d / "scope-a.txt").write_text("x")
mid1, hid1, cls1 = make_verified_handoff(root=root, d=d)
chk("previous handoff classified PASS", cls1 == "PASS")
before = len(list(mission.handoffs_root(d, mid1).glob("handoff-*")))
rc, out, err = do_continue("T-940", mid1, hid1)
chk("continue on a PASS handoff exits 0", rc == 0)
view1 = json.loads(out) if rc == 0 else {}
after = len(list(mission.handoffs_root(d, mid1).glob("handoff-*")))
chk("exactly one new handoff directory was created", after == before + 1)
chk("the new handoff id differs from the previous one",
    view1.get("handoff_id") not in (None, hid1))
chk("packet.json exists for the new handoff", Path(view1.get("packet_path", "")).is_file())
chk("receipt.json exists for the new handoff", Path(view1.get("receipt_path", "")).is_file())
chk("continuation-receipt.json exists for the new handoff",
    Path(view1.get("continuation_receipt_path", "")).is_file())
rc2, out2, err2 = do_continue("T-940", mid1, hid1, key=uniq_key("second"))
chk("a second, distinct continuation request off the SAME PASS handoff also succeeds "
    "(nothing here limits a mission to one continuation)", rc2 == 0)

# =============================================================================================
t("2. BLOCKED refuses continuation")
mid2, hid2, cls2 = make_verified_handoff(root=root, d=d, status="blocked",
                                         result_kwargs={"blocker": "dependency missing"})
chk("previous handoff classified BLOCKED", cls2 == "BLOCKED")
before2 = len(list(mission.handoffs_root(d, mid2).glob("handoff-*")))
rc, out, err = do_continue("T-940", mid2, hid2)
chk("continue on a BLOCKED handoff refuses", rc == 5 and "BLOCKED" in err)
after2 = len(list(mission.handoffs_root(d, mid2).glob("handoff-*")))
chk("no new handoff was created", after2 == before2)

# =============================================================================================
t("3. FAILED refuses continuation")
mid3, hid3, cls3 = make_verified_handoff(root=root, d=d, status="failed")
chk("previous handoff classified FAILED", cls3 == "FAILED")
rc, out, err = do_continue("T-940", mid3, hid3)
chk("continue on a FAILED handoff refuses", rc == 5 and "FAILED" in err)

# =============================================================================================
t("4. NEEDS_OWNER refuses continuation")
mid4, hid4, cls4 = make_verified_handoff(
    root=root, d=d, status="needs_owner",
    result_kwargs={"owner_decision_required": "ambiguous, please decide"})
chk("previous handoff classified NEEDS_OWNER", cls4 == "NEEDS_OWNER")
rc, out, err = do_continue("T-940", mid4, hid4)
chk("continue on a NEEDS_OWNER (self-reported) handoff refuses", rc == 5 and "NEEDS_OWNER" in err)

# =============================================================================================
t("5. NEEDS_OWNER via internally-detected identity mismatch refuses continuation")
mid5, hid5 = make_handoff(root and "T-940" or "T-940")
res5 = make_result(hid5, mid5)
res5["gate"] = "review"  # identity mismatch vs. packet's own gate
rf5 = write_result_file(root, res5)
rc, out, err = do_verify("T-940", mid5, hid5, rf5)
cls5 = json.loads(out)["classification"]
chk("an identity-mismatched result classifies NEEDS_OWNER", cls5 == "NEEDS_OWNER")
rc, out, err = do_continue("T-940", mid5, hid5)
chk("continue on that NEEDS_OWNER handoff refuses", rc == 5 and "NEEDS_OWNER" in err)

# =============================================================================================
t("6. missing verification refuses continuation")
mid6, hid6 = make_handoff()
rc, out, err = do_continue("T-940", mid6, hid6)
chk("continue against a handoff with no verify call yet refuses",
    rc == 5 and "missing verification evidence" in err)

# =============================================================================================
t("7. invalid/stale/malformed verification refuses continuation")
mid7, hid7, cls7 = make_verified_handoff(root=root, d=d)
verification_path = mission.verification_path(d, mid7, hid7)
obj = json.loads(verification_path.read_text())
obj["classification"] = "SORT-OF-PASS"
verification_path.write_text(json.dumps(obj))
rc, out, err = do_continue("T-940", mid7, hid7)
chk("a malformed (unknown) classification value refuses continuation",
    rc == 5 and "malformed verification evidence" in err)

mid7b, hid7b, cls7b = make_verified_handoff(root=root, d=d)
result_path7b = mission.result_path(d, mid7b, hid7b)
result_path7b.unlink()
rc, out, err = do_continue("T-940", mid7b, hid7b)
chk("a verification.json with no matching result.json refuses continuation",
    rc == 5 and "missing test evidence" in err.lower())

# =============================================================================================
t("8. every mission limit — max_attempts exhaustion")
mid8, hid8, cls8 = make_verified_handoff(
    root=root, d=d, create_kwargs={"max_attempts": "1"})
chk("previous handoff classified PASS", cls8 == "PASS")
rc, out, err = do_continue("T-940", mid8, hid8)
chk("continue refuses once max_attempts is already reached",
    rc == 5 and "max_attempts" in err)

# =============================================================================================
t("9. budget exhaustion")
(d / "scope-b.txt").write_text("y")
mid9, hid9, cls9 = make_verified_handoff(
    root=root, d=d, create_kwargs={"budget": "1", "scopes": ("scope-a.txt", "scope-b.txt")},
    handoff_kwargs={"budget": "1"})
chk("previous handoff classified PASS", cls9 == "PASS")
rc, out, err = do_continue("T-940", mid9, hid9, scope="scope-b.txt", budget="1")
chk("continue refuses when the mission's remaining budget is exhausted",
    rc == 5 and "budget" in err.lower())

# =============================================================================================
t("10. attempt exhaustion via repeated continuations")
mid10, hid10, cls10 = make_verified_handoff(
    root=root, d=d, create_kwargs={"max_attempts": "2", "scopes": ("scope-a.txt",
                                                                   "scope-b.txt")})
rc, out, err = do_continue("T-940", mid10, hid10, scope="scope-b.txt")
chk("the second attempt (one continuation) succeeds", rc == 0)
hid10b = json.loads(out)["handoff_id"]
res10b = make_result(hid10b, mid10, root_task_id="T-940", scope="scope-b.txt",
                     changed_files=["scope-b.txt"], invocation_id="inv-continue")
rf10b = write_result_file(root, res10b)
rc, out, err = do_verify("T-940", mid10, hid10b, rf10b)
assert rc == 0 and json.loads(out)["classification"] == "PASS", (rc, out, err)
rc, out, err = do_continue("T-940", mid10, hid10b, scope="scope-a.txt", key=uniq_key("c3"))
chk("a third attempt refuses once max_attempts (2) is exhausted",
    rc == 5 and "max_attempts" in err)

# =============================================================================================
t("11. slice exhaustion (max_slices)")
mid11, hid11, cls11 = make_verified_handoff(
    root=root, d=d, create_kwargs={"max_slices": "1", "scopes": ("scope-a.txt",
                                                                 "scope-b.txt")})
rc, out, err = do_continue("T-940", mid11, hid11, scope="scope-b.txt")
chk("continuing into a SECOND distinct scope refuses once max_slices (1) is reached",
    rc == 5 and "max_slices" in err)
rc, out, err = do_continue("T-940", mid11, hid11, scope="scope-a.txt", key=uniq_key("same"))
chk("continuing into the SAME already-used scope does not consume a new slice",
    rc == 0)

# =============================================================================================
t("12. TTL expiry")
mid12, hid12, cls12 = make_verified_handoff(root=root, d=d, create_kwargs={"ttl": "1"})
time.sleep(1.2)
rc, out, err = do_continue("T-940", mid12, hid12)
chk("continue refuses once ttl_seconds has elapsed since approval",
    rc == 5 and "ttl" in err.lower())

# =============================================================================================
t("13. scope expansion refused")
mid13, hid13, cls13 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid13, hid13, scope="not-an-approved-scope.txt")
chk("a scope that is not one of the mission's approved scopes refuses",
    rc == 5 and "approved scope" in err)

# =============================================================================================
t("14. tool expansion refused")
mid14, hid14, cls14 = make_verified_handoff(root=root, d=d)
packet_path14 = mission.handoff_dir(d, mid14, hid14) / "packet.json"
pobj = json.loads(packet_path14.read_text())
pobj["allowed_tools"] = ["Read", "Edit", "Bash"]
packet_path14.write_text(json.dumps(pobj))
rc, out, err = do_continue("T-940", mid14, hid14)
chk("a previous packet whose allowed_tools no longer matches the contract refuses "
    "(tool boundary must never differ)", rc == 5)

# =============================================================================================
t("15. identity mismatch (wrong executor client) refused")
mid15, hid15, cls15 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid15, hid15, executor_client="test-planner")
chk("an --executor-client that does not match the contract's own executor_client refuses",
    rc == 5 and "identity-mismatched" in err)

# =============================================================================================
t("16. client/session mismatch refused")
mid16, hid16, cls16 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid16, hid16, session="a-different-session")
chk("an --executor-session different from the previous handoff's own session refuses",
    rc == 5 and "session" in err.lower())

# =============================================================================================
t("17. idempotent replay")
mid17, hid17, cls17 = make_verified_handoff(root=root, d=d)
key17 = uniq_key("idem")
rc1, out1, _ = do_continue("T-940", mid17, hid17, key=key17)
rc2, out2, _ = do_continue("T-940", mid17, hid17, key=key17)
chk("a replayed continue (same key, same request) exits 0 both times", rc1 == 0 and rc2 == 0)
v1, v2 = json.loads(out1), json.loads(out2)
chk("both replays report the same new handoff id", v1["handoff_id"] == v2["handoff_id"])
chk("the first call reports replay: false, the second reports replay: true",
    v1["replay"] is False and v2["replay"] is True)
after17 = len(list(mission.handoffs_root(d, mid17).glob("handoff-*")))
chk("no duplicate packet was created by the replay", after17 == 2)  # original + 1 continuation

# =============================================================================================
t("18. conflicting replay (same key, different request)")
mid18, hid18, cls18 = make_verified_handoff(
    root=root, d=d, create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt")})
key18 = uniq_key("conflict")
rc1, out1, _ = do_continue("T-940", mid18, hid18, scope="scope-a.txt", key=key18)
chk("the first call with a fresh key succeeds", rc1 == 0)
rc2, out2, err2 = do_continue("T-940", mid18, hid18, scope="scope-b.txt", key=key18)
chk("reusing the same key with a materially different request refuses",
    rc2 == 5 and ("different" in err2.lower() or "conflict" in err2.lower()))

# =============================================================================================
t("19. deterministic receipt")
mid19, hid19, cls19 = make_verified_handoff(root=root, d=d)
key19 = uniq_key("det")
do_continue("T-940", mid19, hid19, key=key19)
rc1, out1, _ = do_continue("T-940", mid19, hid19, key=key19)
rc2, out2, _ = do_continue("T-940", mid19, hid19, key=key19)
chk("repeated replay JSON output is byte-identical", rc1 == rc2 == 0 and out1 == out2)
new_hid19 = json.loads(out1)["handoff_id"]
creceipt = json.loads(
    (mission.handoff_dir(d, mid19, new_hid19) / "continuation-receipt.json").read_text())
for field in ("previous_handoff_id", "previous_classification", "new_handoff_id",
             "selected_scope", "planner_identity", "executor_identity", "verifier_identity",
             "attempts_before", "attempts_after", "budget_committed_before_usd",
             "budget_committed_after_usd", "stop_condition_evaluation",
             "owner_decision_required"):
    chk(f"continuation receipt contains {field}", field in creceipt)
chk("continuation receipt's previous_handoff_id matches", creceipt["previous_handoff_id"] == hid19)
chk("continuation receipt's previous_classification is PASS",
    creceipt["previous_classification"] == "PASS")
chk("continuation receipt's new_handoff_id matches the returned handoff",
    creceipt["new_handoff_id"] == new_hid19)

# =============================================================================================
t("20. no duplicate packet on replay")
mid20, hid20, cls20 = make_verified_handoff(root=root, d=d)
key20 = uniq_key("nodupe")
before20 = snapshot(root)
do_continue("T-940", mid20, hid20, key=key20)
after_first20 = snapshot(root)
do_continue("T-940", mid20, hid20, key=key20)
after_second20 = snapshot(root)
chk("a replay creates no additional files beyond the first continuation call",
    after_first20 == after_second20)

# =============================================================================================
t("21. no duplicate audit event")
mid21, hid21, cls21 = make_verified_handoff(root=root, d=d)
key21 = uniq_key("noauditdupe")
before_audit21 = mission.audit_path(d, mid21).read_text().count("mission_continue")
do_continue("T-940", mid21, hid21, key=key21)
do_continue("T-940", mid21, hid21, key=key21)
after_audit21 = mission.audit_path(d, mid21).read_text().count("mission_continue")
chk("only one mission_continue audit event was appended despite two identical calls",
    after_audit21 == before_audit21 + 1)

# =============================================================================================
t("22. no duplicate budget or attempt increment on replay")
mid22, hid22, cls22 = make_verified_handoff(root=root, d=d)
key22 = uniq_key("nodoubleincrement")
state_before22 = json.loads(mission.state_path(d, mid22).read_text())
do_continue("T-940", mid22, hid22, key=key22, budget="1")
state_mid22 = json.loads(mission.state_path(d, mid22).read_text())
do_continue("T-940", mid22, hid22, key=key22, budget="1")
state_after22 = json.loads(mission.state_path(d, mid22).read_text())
chk("attempts_used increments exactly once across the replay",
    state_mid22["attempts_used"] == state_before22.get("attempts_used", 0) + 1 and
    state_after22["attempts_used"] == state_mid22["attempts_used"])
chk("budget_committed_usd increments exactly once across the replay",
    state_mid22["budget_committed_usd"] == state_after22["budget_committed_usd"])

# =============================================================================================
t("23. no automatic approval")
mid23, hid23, cls23 = make_verified_handoff(root=root, d=d)
state_before23 = json.loads(mission.state_path(d, mid23).read_text())
do_continue("T-940", mid23, hid23)
state_after23 = json.loads(mission.state_path(d, mid23).read_text())
chk("approval/owner_words/approval_scope_hash are byte-for-byte unchanged by a continuation",
    state_before23["approval"] == state_after23["approval"] and
    state_before23["owner_words"] == state_after23["owner_words"] and
    state_before23["approval_scope_hash"] == state_after23["approval_scope_hash"])

# =============================================================================================
t("24. no automatic completion")
mid24, hid24, cls24 = make_verified_handoff(root=root, d=d)
do_continue("T-940", mid24, hid24)
state_after24 = json.loads(mission.state_path(d, mid24).read_text())
chk("mission state remains 'approved' (never auto-completed) after a continuation",
    state_after24["state"] == "approved")

# =============================================================================================
t("25. no real AI invocation")
src = (CLI / "atlas_mission.py").read_text()
s5_section = src[src.index("# T-051-S5 — safe foreground continuation loop"):]
chk("no subprocess call appears in the S5 section of atlas_mission.py",
    "subprocess.run(" not in s5_section)
chk("no socket/urllib/requests import appears anywhere in atlas_mission.py",
    not any(tok in src for tok in ("import socket", "import urllib", "import requests")))
chk("the only subprocess.run call in the whole file targets atlas-paths (pre-existing, S1)",
    src.count("subprocess.run(") == 1 and "PATHS_RESOLVER" in src)

# =============================================================================================
t("26. engine/core parity")
mid_e, hid_e, cls_e = make_verified_handoff(root=root, d=d, m=mission_cli)
mid_c, hid_c, cls_c = make_verified_handoff(root=root, d=d, m=core_mission_cli)
rc_e, out_e, _ = do_continue("T-940", mid_e, hid_e, m=mission_cli)
rc_c, out_c, _ = do_continue("T-940", mid_c, hid_c, m=core_mission_cli)
view_e, view_c = json.loads(out_e), json.loads(out_c)
chk("engine and core mission continue agree on outcome",
    rc_e == 0 and rc_c == 0 and view_e["previous_classification"] ==
    view_c["previous_classification"] == "PASS")

engine_py = CLI / "atlas_mission.py"
core_py = CORE_CLI / "atlas_mission.py"
chk("engine/cli/atlas_mission.py and core/cli/atlas_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "atlas-mission"
core_cli_file = CORE_CLI / "atlas-mission"
chk("engine/cli/atlas-mission and core/cli/atlas-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())

# =============================================================================================
t("27. protected T-050 files remain untouched")
PROTECTED = [
    CLI / "atlas-coordinator", CORE_CLI / "atlas-coordinator",
    CLI / "atlas_coordination.py", CORE_CLI / "atlas_coordination.py",
    CLI / "atlas-handoff", CORE_CLI / "atlas-handoff",
    REPO / "governance" / "policies" / "handoff-transports.yaml",
    REPO / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())

chk("atlas_mission.py never actually loads atlas-coordinator or atlas_coordination as a module",
    '_load_sibling("atlas-coordinator")' not in src and
    "import atlas_coordination" not in src and "from atlas_coordination" not in src)

# =============================================================================================
t("28. unknown previous handoff refusal")
mid28, _hid28 = make_handoff()
rc, out, err = do_continue("T-940", mid28, "handoff-doesnotexist")
chk("continue against an unknown previous handoff id refuses",
    rc == 4 and "handoff" in err)

# =============================================================================================
t("29. closed mission refusal")
mid29, hid29, cls29 = make_verified_handoff(root=root, d=d)
obj29 = json.loads(mission.state_path(d, mid29).read_text())
obj29["state"] = "blocked"
mission.state_path(d, mid29).write_text(json.dumps(obj29))
rc, out, err = do_continue("T-940", mid29, hid29)
chk("continue against a closed (blocked) mission refuses", rc == 5 and "closed" in err)

# =============================================================================================
t("30. previous handoff belonging to a different mission (cross-mission identity mismatch)")
mid30a, hid30a, cls30a = make_verified_handoff(root=root, d=d)
mid30b, hid30b = make_handoff()
# Try to continue mission B using a handoff id that only exists under mission A.
rc, out, err = do_continue("T-940", mid30b, hid30a)
chk("continuing a mission with a handoff id from a different mission refuses",
    rc == 4)  # no such handoff under mission30b's own directory

# =============================================================================================
t("31. no scope given refuses")
mid31, hid31, cls31 = make_verified_handoff(root=root, d=d)
rc, out, err = run(mission_cli.cmd_continue,
                   ["T-940", mid31, hid31, "--executor-client", "test-executor",
                    "--executor-session", "sess-fixed", "--invocation-id", "inv-x",
                    "--gate", "execute", "--slice-budget-usd", "1", "--idempotency-key",
                    uniq_key("noscope")])
chk("a missing --scope refuses", rc == 2)

# =============================================================================================
t("32. no idempotency-key refuses")
mid32, hid32, cls32 = make_verified_handoff(root=root, d=d)
rc, out, err = run(mission_cli.cmd_continue,
                   ["T-940", mid32, hid32, "--scope", "scope-a.txt", "--executor-client",
                    "test-executor", "--executor-session", "sess-fixed", "--invocation-id",
                    "inv-x", "--gate", "execute", "--slice-budget-usd", "1"])
chk("a missing --idempotency-key refuses", rc == 2)

# =============================================================================================
t("33. invalid gate refuses")
mid33, hid33, cls33 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid33, hid33, gate="not-a-real-gate")
chk("an invalid gate refuses", rc == 2)

# =============================================================================================
t("34. negative / non-numeric slice budget refuses")
mid34, hid34, cls34 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid34, hid34, budget="-1")
chk("a negative --slice-budget-usd refuses", rc == 2)
rc, out, err = do_continue("T-940", mid34, hid34, budget="not-a-number", key=uniq_key("nan"))
chk("a non-numeric --slice-budget-usd refuses", rc == 2)

# =============================================================================================
t("35. credential-shaped scope value refuses")
mid35, hid35, cls35 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid35, hid35,
                           scope="sk-ant-" + "a" * 30)
chk("a credential-shaped --scope value refuses before anything is written",
    rc == 2)

# =============================================================================================
t("36. no automatic ticket selection — root_task_id mismatch refuses")
mid36, hid36, cls36 = make_verified_handoff(root=root, d=d)
task_dir36 = mission.resolve_task_dir("T-940")
rc = None
try:
    mission.mission_continue(task_dir36, "T-999-WRONG", mid36, hid36, "scope-a.txt",
                             "test-executor", "sess-fixed", "inv-x", "execute", "1",
                             uniq_key("wrongticket"))
except mission.MissionError as e:
    rc = e.code
chk("a mismatched root_task_id refuses rather than silently selecting a different ticket",
    rc == 4)

# =============================================================================================
t("37. never marks mission completed — state enum never gains a new value here")
mid37, hid37, cls37 = make_verified_handoff(root=root, d=d)
do_continue("T-940", mid37, hid37)
state37 = json.loads(mission.state_path(d, mid37).read_text())
chk("mission state after a successful continuation is still one of the declared "
    "MISSION_STATES", state37["state"] in mission.MISSION_STATES)
chk("mission state is exactly 'approved', never 'completed' (not a declared state at all)",
    state37["state"] == "approved" and "completed" not in mission.MISSION_STATES)

# =============================================================================================
t("38. no infinite loop — one call produces exactly one handoff, never a cascade")
mid38, hid38, cls38 = make_verified_handoff(root=root, d=d)
before38 = len(list(mission.handoffs_root(d, mid38).glob("handoff-*")))
do_continue("T-940", mid38, hid38)
after38 = len(list(mission.handoffs_root(d, mid38).glob("handoff-*")))
chk("exactly one new handoff was created by one continuation call, no cascade",
    after38 == before38 + 1)
src_body = src[src.index("def mission_continue("):]
src_body = src_body[:src_body.index("\n\n\ndef ") if "\n\n\ndef " in src_body else len(src_body)]
chk("mission_continue never calls itself recursively",
    src_body.count("mission_continue(") <= 1)

# =============================================================================================
t("39. next slice remains inside the original mission contract — packet mirrors contract "
   "tools/budget exactly")
mid39, hid39, cls39 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid39, hid39)
new_hid39 = json.loads(out)["handoff_id"]
packet39 = json.loads((mission.handoff_dir(d, mid39, new_hid39) / "packet.json").read_text())
contract39, _ = mission.load_mission(d, mid39)
chk("the new packet's allowed_tools exactly matches the contract's own allowed_tools",
    packet39["allowed_tools"] == contract39["allowed_tools"])
chk("the new packet's denied_tools exactly matches the contract's own denied_tools",
    packet39["denied_tools"] == contract39["denied_tools"])
chk("the new packet's budget_usd exactly matches the contract's own budget_usd",
    packet39["budget_usd"] == contract39["budget_usd"])

# =============================================================================================
t("40. approval scope hash revalidation — stale hash refuses")
mid40, hid40, cls40 = make_verified_handoff(root=root, d=d)
state_obj40 = json.loads(mission.state_path(d, mid40).read_text())
state_obj40["approval_scope_hash"] = "0" * 64
mission.state_path(d, mid40).write_text(json.dumps(state_obj40))
rc, out, err = do_continue("T-940", mid40, hid40)
chk("a stale/tampered approval_scope_hash refuses continuation",
    rc == 5 and "approval" in err.lower())

# =============================================================================================
t("41. planner/executor/verifier routes are all resolved before writing")
mid41, hid41, cls41 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid41, hid41)
new_hid41 = json.loads(out)["handoff_id"]
receipt41 = json.loads((mission.handoff_dir(d, mid41, new_hid41) / "receipt.json").read_text())
chk("the new receipt records a planner_route", "planner_route" in receipt41)
chk("the new receipt records an executor_route", "executor_route" in receipt41)
chk("the new receipt records a verifier_route", "verifier_route" in receipt41)

# =============================================================================================
t("42. no lease, claim, dispatch, send, or V6 handoff record created")
mid42, hid42, cls42 = make_verified_handoff(root=root, d=d)
before42 = snapshot(root)
do_continue("T-940", mid42, hid42)
after42 = snapshot(root)
new_paths42 = [p for p in after42 if p not in before42]
chk("every new path from a continuation call lives under this mission's own handoffs/ "
    "or state/audit files",
    all("/mission/" in p or p.endswith(".lock") for p in new_paths42))
chk("no coordination/ directory exists anywhere under the fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the fixture root",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("43. previous handoff's own packet/verification are never rewritten")
mid43, hid43, cls43 = make_verified_handoff(root=root, d=d)
packet_before43 = (mission.handoff_dir(d, mid43, hid43) / "packet.json").read_text()
verification_before43 = (mission.handoff_dir(d, mid43, hid43) / "verification.json").read_text()
do_continue("T-940", mid43, hid43)
packet_after43 = (mission.handoff_dir(d, mid43, hid43) / "packet.json").read_text()
verification_after43 = (mission.handoff_dir(d, mid43, hid43) / "verification.json").read_text()
chk("the previous handoff's packet.json is byte-for-byte unchanged",
    packet_before43 == packet_after43)
chk("the previous handoff's verification.json is byte-for-byte unchanged",
    verification_before43 == verification_after43)

# =============================================================================================
t("44. owner decision requirement is always present and explicit")
mid44, hid44, cls44 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid44, hid44)
new_hid44 = json.loads(out)["handoff_id"]
creceipt44 = json.loads(
    (mission.handoff_dir(d, mid44, new_hid44) / "continuation-receipt.json").read_text())
chk("owner_decision_required is a non-empty string on every continuation receipt",
    isinstance(creceipt44["owner_decision_required"], str) and
    creceipt44["owner_decision_required"].strip())

# =============================================================================================
t("45. mission show/status reflect the new handoff without any extra state change")
mid45, hid45, cls45 = make_verified_handoff(root=root, d=d)
do_continue("T-940", mid45, hid45)
rc, out, err = run(mission_cli.cmd_show, ["T-940", mid45, "--json"])
view45 = json.loads(out)
chk("mission show still reports state 'approved' after a continuation",
    view45["state"] == "approved")
chk("mission show's handoffs list grew by exactly one entry",
    len(view45["handoffs"]) == 2)

# =============================================================================================
t("46. missing --executor-client / --executor-session / --invocation-id all refuse")
mid46, hid46, cls46 = make_verified_handoff(root=root, d=d)
rc, out, err = run(mission_cli.cmd_continue,
                   ["T-940", mid46, hid46, "--scope", "scope-a.txt",
                    "--executor-session", "sess-fixed", "--invocation-id", "inv-x",
                    "--gate", "execute", "--slice-budget-usd", "1",
                    "--idempotency-key", uniq_key("noexec")])
chk("a missing --executor-client refuses", rc == 2)
rc, out, err = run(mission_cli.cmd_continue,
                   ["T-940", mid46, hid46, "--scope", "scope-a.txt",
                    "--executor-client", "test-executor", "--invocation-id", "inv-x",
                    "--gate", "execute", "--slice-budget-usd", "1",
                    "--idempotency-key", uniq_key("nosess")])
chk("a missing --executor-session refuses", rc == 2)
rc, out, err = run(mission_cli.cmd_continue,
                   ["T-940", mid46, hid46, "--scope", "scope-a.txt",
                    "--executor-client", "test-executor", "--executor-session", "sess-fixed",
                    "--gate", "execute", "--slice-budget-usd", "1",
                    "--idempotency-key", uniq_key("noinv")])
chk("a missing --invocation-id refuses", rc == 2)

# =============================================================================================
t("47. mission validate remains unaffected by a continuation")
mid47, hid47, cls47 = make_verified_handoff(root=root, d=d)
rc47a, out47a, _ = run(mission_cli.cmd_validate, ["T-940", mid47, "--json"])
do_continue("T-940", mid47, hid47)
rc47b, out47b, _ = run(mission_cli.cmd_validate, ["T-940", mid47, "--json"])
chk("mission validate still reports valid: true after a continuation",
    json.loads(out47a)["valid"] is True and json.loads(out47b)["valid"] is True)

# =============================================================================================
t("48. per-handoff independence — verifying the new handoff works normally")
mid48, hid48, cls48 = make_verified_handoff(root=root, d=d)
rc, out, err = do_continue("T-940", mid48, hid48)
new_hid48 = json.loads(out)["handoff_id"]
res48 = make_result(new_hid48, mid48, root_task_id="T-940", executor_session="sess-fixed",
                    invocation_id="inv-continue")
rf48 = write_result_file(root, res48)
rc48, out48, err48 = do_verify("T-940", mid48, new_hid48, rf48)
chk("the newly-created continuation handoff can itself be verified normally",
    rc48 == 0 and json.loads(out48)["classification"] == "PASS")

# =============================================================================================
t("49. a chain of two continuations (PASS -> continue -> PASS -> continue) works")
mid49, hid49, cls49 = make_verified_handoff(
    root=root, d=d, create_kwargs={"max_attempts": "5", "max_slices": "5",
                                   "scopes": ("scope-a.txt", "scope-b.txt")})
rc, out, err = do_continue("T-940", mid49, hid49, scope="scope-b.txt")
chk("the first continuation succeeds", rc == 0)
hid49b = json.loads(out)["handoff_id"]
res49b = make_result(hid49b, mid49, root_task_id="T-940", scope="scope-b.txt",
                     changed_files=["scope-b.txt"], invocation_id="inv-continue")
rf49b = write_result_file(root, res49b)
rc, out, err = do_verify("T-940", mid49, hid49b, rf49b)
chk("verifying the first continuation's handoff succeeds", rc == 0 and
    json.loads(out)["classification"] == "PASS")
rc, out, err = do_continue("T-940", mid49, hid49b, scope="scope-a.txt", key=uniq_key("chain2"))
chk("a second continuation off the first continuation's own PASS succeeds", rc == 0)

# =============================================================================================
t("50. everything under T-051-S1/S2/S3/S4 remains green")
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "ATLAS_ADAPTERS", "ATLAS_HANDOFF_TRANSPORTS")}
r1 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-contract.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-contract.py (T-051-S1) exits 0", r1.returncode == 0)
r2 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-routing.py (T-051-S2) exits 0", r2.returncode == 0)
r3 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-handoff.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-handoff.py (T-051-S3) exits 0", r3.returncode == 0)
r4 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-result.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-result.py (T-051-S4) exits 0", r4.returncode == 0)

t("51. all T-050 tests remain green")
r5 = subprocess.run(
    [sys.executable, str(REPO / "tests" / "test-coordinator-conflict-protection.py")],
    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-conflict-protection.py exits 0", r5.returncode == 0)
r6 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-routing.py exits 0", r6.returncode == 0)
r7 = subprocess.run([sys.executable, str(REPO / "tests" / "test-cli-source-drift.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-cli-source-drift.py exits 0", r7.returncode == 0)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(1 if failed else 0)
