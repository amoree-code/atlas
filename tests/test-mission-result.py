#!/usr/bin/env python3
"""tests/test-mission-result.py — T-051-S4: the structured result packet and verifier gate
(`mission verify` / `mission result`) on top of the T-051-S1 contract, T-051-S2 role
resolution, and T-051-S3 bounded handoff.

Every scenario runs against a disposable ATLAS_HOME, plus a disposable adapter registry and
a disposable transport registry (via ATLAS_ADAPTERS / ATLAS_HANDOFF_TRANSPORTS), exactly like
`test-mission-handoff.py`'s own fixture pattern. Nothing here reads or writes the real
`adapters/`, the real `governance/policies/handoff-transports.yaml`, any real T-050
record, or any real mission record.

This file proves the S4 scope only: `mission verify` validates one executor-returned result
against its own T-051-S3 packet and classifies it into exactly one of PASS / BLOCKED / FAILED
/ NEEDS_OWNER, persisting both the raw result and the verification evidence only under that
handoff's own directory. `mission result` is the paired read-only inspector. No planner or
executor is ever invoked. No lease, claim, or V6 handoff record is ever created. Mission
approval and state are never touched. No continuation loop exists.
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
# Fixture registries — same pattern as test-mission-handoff.py.
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


def new_fixture(ticket_id="T-930"):
    tmp = Path(tempfile.mkdtemp(prefix="t051-s4-"))
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-result tests\nstate: active\n"
        "project: demo\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id))

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    transports_path = tmp / "handoff-transports.yaml"

    for c in ("test-planner", "test-executor"):
        write_adapter(adapters_dir, c)
    write_transports(transports_path, ["test-planner", "test-executor"])

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
            "test-planner", "--budget-usd", budget, "--max-slices", max_slices,
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


def make_handoff(task_id="T-930", m=None, create_kwargs=None, handoff_kwargs=None):
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


def result_hash(handoff_id, mission_id, root_task_id="T-930", status="pass",
                changed_files=("scope-a.txt",), tests_field=("pytest ok",),
                summary="did the thing"):
    """Mirrors `atlas_mission._result_content_hash` exactly: `tests` is used AS-IS (whatever
    type the result actually declares), never coerced to a list."""
    material = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "status": status, "changed_files": sorted(changed_files), "tests": tests_field,
        "summary": summary,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def make_result(handoff_id, mission_id, root_task_id="T-930",
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


# =============================================================================================
t("1. PASS classification")
root, d, adapters_dir, transports_path = new_fixture()
(d / "scope-a.txt").write_text("x")
mid, hid = make_handoff()
res = make_result(hid, mid)
rf = write_result_file(root, res)
rc, out, err = do_verify("T-930", mid, hid, rf)
chk("a fully valid result exits 0", rc == 0)
view = json.loads(out) if rc == 0 else {}
chk("classification is PASS", view.get("classification") == "PASS")
chk("result.json was written on disk", Path(view.get("result_path", "")).is_file())
chk("verification.json was written on disk", Path(view.get("verification_path", "")).is_file())

# =============================================================================================
t("2. BLOCKED classification (self-reported)")
mid2, hid2 = make_handoff()
res2 = make_result(hid2, mid2, status="blocked", blocker="dependency missing")
rf2 = write_result_file(root, res2)
rc, out, err = do_verify("T-930", mid2, hid2, rf2)
chk("a self-reported blocked result exits 0", rc == 0)
chk("classification is BLOCKED", json.loads(out)["classification"] == "BLOCKED")

# =============================================================================================
t("3. FAILED classification (self-reported)")
mid3, hid3 = make_handoff()
res3 = make_result(hid3, mid3, status="failed")
rf3 = write_result_file(root, res3)
rc, out, err = do_verify("T-930", mid3, hid3, rf3)
chk("a self-reported failed result exits 0", rc == 0)
chk("classification is FAILED", json.loads(out)["classification"] == "FAILED")

# =============================================================================================
t("4. NEEDS_OWNER classification (self-reported)")
mid4, hid4 = make_handoff()
res4 = make_result(hid4, mid4, status="needs_owner",
                   owner_decision_required="ambiguous approach, please decide")
rf4 = write_result_file(root, res4)
rc, out, err = do_verify("T-930", mid4, hid4, rf4)
chk("a self-reported needs_owner result exits 0", rc == 0)
chk("classification is NEEDS_OWNER", json.loads(out)["classification"] == "NEEDS_OWNER")

# =============================================================================================
t("5. missing result refusal")
mid5, hid5 = make_handoff()
rc, out, err = do_verify("T-930", mid5, hid5, str(root / "does-not-exist.json"))
chk("a nonexistent --result-file refuses", rc == 4 and "missing result" in err)

# =============================================================================================
t("6. malformed result refusal (not JSON)")
mid6, hid6 = make_handoff()
bad_path = root / "notjson.json"
bad_path.write_text("{not valid json")
rc, out, err = do_verify("T-930", mid6, hid6, str(bad_path))
chk("a non-JSON result file refuses", rc == 2 and "malformed result" in err)

# =============================================================================================
t("7. malformed result refusal (not an object)")
mid7, hid7 = make_handoff()
arr_path = root / "arr.json"
arr_path.write_text("[1, 2, 3]")
rc, out, err = do_verify("T-930", mid7, hid7, str(arr_path))
chk("a JSON array (not object) result file refuses", rc == 2 and "malformed result" in err)

# =============================================================================================
t("8. malformed result refusal (missing required field)")
mid8, hid8 = make_handoff()
res8 = make_result(hid8, mid8)
del res8["summary"]
rf8 = write_result_file(root, res8)
rc, out, err = do_verify("T-930", mid8, hid8, rf8)
chk("a result missing a required field refuses", rc == 2 and "missing required field" in err)

# =============================================================================================
t("9. invalid status refusal")
mid9, hid9 = make_handoff()
res9 = make_result(hid9, mid9)
res9["status"] = "maybe"
rf9 = write_result_file(root, res9)
rc, out, err = do_verify("T-930", mid9, hid9, rf9)
chk("an unknown status value refuses", rc == 2 and "invalid status" in err)

# =============================================================================================
t("10. malformed result_sha256 refusal")
mid10, hid10 = make_handoff()
res10 = make_result(hid10, mid10)
res10["result_sha256"] = "not-a-hash"
rf10 = write_result_file(root, res10)
rc, out, err = do_verify("T-930", mid10, hid10, rf10)
chk("a malformed result_sha256 refuses", rc == 2 and "malformed result" in err)

# =============================================================================================
t("11. blocked status without a blocker field refuses")
mid11, hid11 = make_handoff()
res11 = make_result(hid11, mid11, status="blocked")
rf11 = write_result_file(root, res11)
rc, out, err = do_verify("T-930", mid11, hid11, rf11)
chk("status blocked with no blocker field refuses", rc == 2 and "blocker" in err)

# =============================================================================================
t("12. needs_owner status without owner_decision_required refuses")
mid12, hid12 = make_handoff()
res12 = make_result(hid12, mid12, status="needs_owner")
rf12 = write_result_file(root, res12)
rc, out, err = do_verify("T-930", mid12, hid12, rf12)
chk("status needs_owner with no owner_decision_required refuses",
    rc == 2 and "owner_decision_required" in err)

# =============================================================================================
t("13. every identity mismatch")
mid13, hid13 = make_handoff()
for field, bad_value in (("handoff_id", "handoff-wrong"), ("mission_id", "mission-wrong"),
                         ("root_task_id", "T-999"), ("executor_client", "test-planner"),
                         ("executor_session", "sess-wrong"), ("invocation_id", "inv-wrong"),
                         ("gate", "review")):
    res_bad = make_result(hid13, mid13)
    res_bad[field] = bad_value
    rf_bad = write_result_file(root, res_bad)
    rc, out, err = do_verify("T-930", mid13, hid13, rf_bad)
    view = json.loads(out) if rc == 0 else {}
    chk(f"a mismatched {field} classifies NEEDS_OWNER (never silently accepted)",
        rc == 0 and view.get("classification") == "NEEDS_OWNER")

# =============================================================================================
t("14. scope expansion")
mid14, hid14 = make_handoff(create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt")})
(d / "scope-b.txt").write_text("y")
res14 = make_result(hid14, mid14, changed_files=["scope-a.txt", "scope-b.txt"],
                    tests=["pytest ok"])
rf14 = write_result_file(root, res14)
rc, out, err = do_verify("T-930", mid14, hid14, rf14)
chk("changed_files outside the approved single scope classifies BLOCKED",
    rc == 0 and json.loads(out)["classification"] == "BLOCKED")

mid14b, hid14b = make_handoff()
res14b = make_result(hid14b, mid14b, changed_files=["../etc/passwd"])
rf14b = write_result_file(root, res14b)
rc, out, err = do_verify("T-930", mid14b, hid14b, rf14b)
chk("an unsafe/traversal changed_files path classifies BLOCKED, not accepted",
    rc == 0 and json.loads(out)["classification"] == "BLOCKED")

# =============================================================================================
t("15. hash mismatch")
mid15, hid15 = make_handoff()
res15 = make_result(hid15, mid15, bad_hash=True)
rf15 = write_result_file(root, res15)
rc, out, err = do_verify("T-930", mid15, hid15, rf15)
chk("a result_sha256 that does not match the recomputed hash classifies FAILED",
    rc == 0 and json.loads(out)["classification"] == "FAILED")

# =============================================================================================
t("16. missing test evidence")
mid16, hid16 = make_handoff()
res16 = make_result(hid16, mid16, tests=[])
rf16 = write_result_file(root, res16)
rc, out, err = do_verify("T-930", mid16, hid16, rf16)
chk("empty tests list classifies NEEDS_OWNER",
    rc == 0 and json.loads(out)["classification"] == "NEEDS_OWNER")

mid16b, hid16b = make_handoff()
res16b = make_result(hid16b, mid16b, tests=[""], tests_list=False)
rf16b = write_result_file(root, res16b)
rc, out, err = do_verify("T-930", mid16b, hid16b, rf16b)
chk("empty string tests classifies NEEDS_OWNER",
    rc == 0 and json.loads(out)["classification"] == "NEEDS_OWNER")

# =============================================================================================
t("17. budget and cost violations")
mid17, hid17 = make_handoff(handoff_kwargs={"budget": "1"})
res17 = make_result(hid17, mid17, reported_cost_usd=5.0)
rf17 = write_result_file(root, res17)
rc, out, err = do_verify("T-930", mid17, hid17, rf17)
chk("reported_cost_usd exceeding the slice budget classifies NEEDS_OWNER",
    rc == 0 and json.loads(out)["classification"] == "NEEDS_OWNER")

mid17b, hid17b = make_handoff(handoff_kwargs={"budget": "1"})
res17b = make_result(hid17b, mid17b, reported_cost_usd=1.0)
rf17b = write_result_file(root, res17b)
rc, out, err = do_verify("T-930", mid17b, hid17b, rf17b)
chk("reported_cost_usd exactly at the slice budget still classifies PASS",
    rc == 0 and json.loads(out)["classification"] == "PASS")

mid17c, hid17c = make_handoff()
res17c = make_result(hid17c, mid17c)
res17c["reported_cost_usd"] = -1
rf17c = write_result_file(root, res17c)
rc, out, err = do_verify("T-930", mid17c, hid17c, rf17c)
chk("a negative reported_cost_usd refuses as malformed", rc == 2 and "malformed result" in err)

# =============================================================================================
t("18. credential-shaped content refusal")
mid18, hid18 = make_handoff()
res18 = make_result(hid18, mid18, summary="here is a key: sk-ant-" + "a" * 30)
rf18 = write_result_file(root, res18)
rc, out, err = do_verify("T-930", mid18, hid18, rf18)
chk("a credential-shaped value in the result refuses, nothing is persisted",
    rc == 2 and "nothing was written" in err.lower())
chk("no result.json was written for the credential-shaped attempt",
    not (mission.handoff_dir(d, mid18, hid18) / "result.json").is_file())

# =============================================================================================
t("19. idempotent replay")
mid19, hid19 = make_handoff()
res19 = make_result(hid19, mid19)
rf19 = write_result_file(root, res19)
key19 = uniq_key("idem")
rc1, out1, _ = do_verify("T-930", mid19, hid19, rf19, key=key19)
rc2, out2, _ = do_verify("T-930", mid19, hid19, rf19, key=key19)
chk("a replayed verify (same key, same file) exits 0 both times", rc1 == 0 and rc2 == 0)
v1, v2 = json.loads(out1), json.loads(out2)
chk("a replayed verify returns the identical classification", v1["classification"] == v2["classification"])
chk("the first call reports replay: false, the second reports replay: true",
    v1["replay"] is False and v2["replay"] is True)

# =============================================================================================
t("20. conflicting replay (same key, different result content)")
mid20, hid20 = make_handoff()
res20a = make_result(hid20, mid20, status="pass")
res20b = make_result(hid20, mid20, status="failed")
rf20a = write_result_file(root, res20a)
rf20b = write_result_file(root, res20b)
key20 = uniq_key("conflict")
rc1, out1, _ = do_verify("T-930", mid20, hid20, rf20a, key=key20)
chk("the first call with a fresh key succeeds", rc1 == 0)
rc2, out2, err2 = do_verify("T-930", mid20, hid20, rf20b, key=key20)
chk("reusing the same key with different result content refuses",
    rc2 == 5 and ("different" in err2.lower() or "conflict" in err2.lower()))

# =============================================================================================
t("21. deterministic output")
mid21, hid21 = make_handoff()
res21 = make_result(hid21, mid21)
rf21 = write_result_file(root, res21)
key21 = uniq_key("det")
do_verify("T-930", mid21, hid21, rf21, key=key21)
rc1, out1, _ = do_verify("T-930", mid21, hid21, rf21, key=key21)
rc2, out2, _ = do_verify("T-930", mid21, hid21, rf21, key=key21)
chk("repeated replay JSON output is byte-identical", rc1 == rc2 == 0 and out1 == out2)
chk("JSON output round-trips", json.loads(out1) == json.loads(out2))

# =============================================================================================
t("22. no automatic continuation")
mid22, hid22 = make_handoff(create_kwargs={"scopes": ("scope-a.txt", "scope-b.txt")})
before_handoffs = len(list(mission.handoffs_root(d, mid22).glob("handoff-*")))
res22 = make_result(hid22, mid22)
rf22 = write_result_file(root, res22)
do_verify("T-930", mid22, hid22, rf22)
after_handoffs = len(list(mission.handoffs_root(d, mid22).glob("handoff-*")))
chk("verify never creates a new handoff on its own", before_handoffs == after_handoffs == 1)

# =============================================================================================
t("23. no automatic approval, no automatic completion")
mid23, hid23 = make_handoff()
state_before = json.loads(mission.state_path(d, mid23).read_text())
res23 = make_result(hid23, mid23)
rf23 = write_result_file(root, res23)
do_verify("T-930", mid23, hid23, rf23)
state_after = json.loads(mission.state_path(d, mid23).read_text())
chk("mission state.json is byte-for-byte unchanged by a verify call", state_before == state_after)
chk("mission state remains 'approved' (never auto-completed)", state_after["state"] == "approved")

# =============================================================================================
t("24. classification and evidence persisted only under the handoff's own directory")
mid24, hid24 = make_handoff()
before = snapshot(root)
res24 = make_result(hid24, mid24)
rf24 = write_result_file(root, res24)
do_verify("T-930", mid24, hid24, rf24)
after = snapshot(root)
new_paths = [p for p in after if p not in before and str(root / p) != rf24
            and not str(p).endswith(Path(rf24).name)]
handoff_prefix = f"projects/demo/tickets/T-930/mission/{mid24}/handoffs/{hid24}/"
chk("every new path from a verify call lives under this handoff's own directory",
    all(p.startswith(handoff_prefix) for p in new_paths))
chk("no coordination/ directory exists anywhere under the fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the fixture root",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("25. mission result read-only inspector")
mid25, hid25 = make_handoff()
rc, out, err = run(mission_cli.cmd_result, ["T-930", mid25, hid25, "--json"])
chk("mission result on a handoff with no submitted result exits 0", rc == 0)
chk("has_result is false before any verify call", json.loads(out)["has_result"] is False)

res25 = make_result(hid25, mid25)
rf25 = write_result_file(root, res25)
do_verify("T-930", mid25, hid25, rf25)
rc, out, err = run(mission_cli.cmd_result, ["T-930", mid25, hid25, "--json"])
chk("mission result reflects has_result true after a verify call", json.loads(out)["has_result"] is True)
chk("mission result reflects the same classification verify recorded",
    json.loads(out)["classification"] == "PASS")

before_result = snapshot(root)
run(mission_cli.cmd_result, ["T-930", mid25, hid25, "--json"])
after_result = snapshot(root)
chk("mission result never writes anything", before_result == after_result)

# =============================================================================================
t("26. unknown handoff refusal")
mid26, _hid26 = make_handoff()
res26 = make_result("handoff-doesnotexist", mid26)
rf26 = write_result_file(root, res26)
rc, out, err = do_verify("T-930", mid26, "handoff-doesnotexist", rf26)
chk("verify against an unknown handoff id refuses", rc == 4 and "handoff" in err)
rc, out, err = run(mission_cli.cmd_result, ["T-930", mid26, "handoff-doesnotexist", "--json"])
chk("result against an unknown handoff id refuses", rc == 4)

# =============================================================================================
t("27. closed mission refusal")
mid27, hid27 = make_handoff()
obj = json.loads(mission.state_path(d, mid27).read_text())
obj["state"] = "blocked"
mission.state_path(d, mid27).write_text(json.dumps(obj))
res27 = make_result(hid27, mid27)
rf27 = write_result_file(root, res27)
rc, out, err = do_verify("T-930", mid27, hid27, rf27)
chk("verify against a closed (blocked) mission refuses", rc == 5 and "closed" in err)

# =============================================================================================
t("28. oversized result file refusal")
mid28, hid28 = make_handoff()
huge_path = root / "huge.json"
huge_path.write_text(json.dumps({"padding": "x" * (mission.MAX_RESULT_FILE_BYTES + 10)}))
rc, out, err = do_verify("T-930", mid28, hid28, str(huge_path))
chk("an oversized result file refuses", rc == 2 and "size cap" in err)

# =============================================================================================
t("29. no AI invocation")
src = (CLI / "atlas_mission.py").read_text()
s4_section = src[src.index("# T-051-S4 — structured result and verifier gate"):]
chk("no subprocess call appears in the S4 section of atlas_mission.py",
    "subprocess.run(" not in s4_section)
chk("no socket/urllib/requests import appears anywhere in atlas_mission.py",
    not any(tok in src for tok in ("import socket", "import urllib", "import requests")))
chk("the only subprocess.run call in the whole file targets atlas-paths (pre-existing, S1)",
    src.count("subprocess.run(") == 1 and "PATHS_RESOLVER" in src)

# =============================================================================================
t("30. core/engine parity")
mid_e, hid_e = make_handoff(m=mission_cli)
mid_c, hid_c = make_handoff(m=core_mission_cli)
res_e = make_result(hid_e, mid_e)
res_c = make_result(hid_c, mid_c)
rf_e = write_result_file(root, res_e)
rf_c = write_result_file(root, res_c)
rc_e, out_e, _ = do_verify("T-930", mid_e, hid_e, rf_e, m=mission_cli)
rc_c, out_c, _ = do_verify("T-930", mid_c, hid_c, rf_c, m=core_mission_cli)
view_e, view_c = json.loads(out_e), json.loads(out_c)
chk("engine and core mission verify agree on classification",
    rc_e == 0 and rc_c == 0 and view_e["classification"] == view_c["classification"] == "PASS")

engine_py = CLI / "atlas_mission.py"
core_py = CORE_CLI / "atlas_mission.py"
chk("engine/cli/atlas_mission.py and core/cli/atlas_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "atlas-mission"
core_cli_file = CORE_CLI / "atlas-mission"
chk("engine/cli/atlas-mission and core/cli/atlas-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())

# =============================================================================================
t("31. canonical atlas parity — no dispatcher edit was required")
atlas_text = (CLI / "atlas").read_text()
core_atlas_text = (CORE_CLI / "atlas").read_text()
chk("'mission' still sits in engine/cli/atlas's generic exec-by-name case arm",
    "mission|" in atlas_text or "|mission" in atlas_text)
chk("'mission' still sits in core/cli/atlas's generic exec-by-name case arm",
    "mission|" in core_atlas_text or "|mission" in core_atlas_text)

# =============================================================================================
t("32. protected files untouched")
PROTECTED = [
    CLI / "atlas-coordinator", CORE_CLI / "atlas-coordinator",
    CLI / "atlas_coordination.py", CORE_CLI / "atlas_coordination.py",
    CLI / "atlas-handoff", CORE_CLI / "atlas-handoff",
    REPO / "governance" / "policies" / "handoff-transports.yaml",
    REPO / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())

src_all = (CLI / "atlas_mission.py").read_text()
chk("atlas_mission.py never actually loads atlas-coordinator or atlas_coordination as a "
    "module (only ever mentions the coordinator in prose comments)",
    '_load_sibling("atlas-coordinator")' not in src_all and
    "import atlas_coordination" not in src_all and
    "from atlas_coordination" not in src_all)

# =============================================================================================
t("33. missing scope field refusal")
mid33, hid33 = make_handoff()
res33 = make_result(hid33, mid33)
del res33["scope"]
rf33 = write_result_file(root, res33)
rc, out, err = do_verify("T-930", mid33, hid33, rf33)
chk("a result missing the scope field refuses as malformed",
    rc == 2 and "missing required field" in err)

# =============================================================================================
t("34. no idempotency-key refusal")
mid34, hid34 = make_handoff()
res34 = make_result(hid34, mid34)
rf34 = write_result_file(root, res34)
rc, out, err = run(mission_cli.cmd_verify,
                   ["T-930", mid34, hid34, "--result-file", rf34])
chk("a missing --idempotency-key refuses", rc == 2)

# =============================================================================================
t("35. no --result-file refusal")
mid35, hid35 = make_handoff()
rc, out, err = run(mission_cli.cmd_verify,
                   ["T-930", mid35, hid35, "--idempotency-key", uniq_key("k")])
chk("a missing --result-file refuses", rc == 2)

# =============================================================================================
t("36. non-string tests entries refuse as malformed")
mid36, hid36 = make_handoff()
res36 = make_result(hid36, mid36)
res36["tests"] = [1, 2, 3]
rf36 = write_result_file(root, res36)
rc, out, err = do_verify("T-930", mid36, hid36, rf36)
chk("a tests list of non-strings refuses as malformed", rc == 2 and "malformed result" in err)

# =============================================================================================
t("37. changed_files with non-string entries refuse as malformed")
mid37, hid37 = make_handoff()
res37 = make_result(hid37, mid37)
res37["changed_files"] = [1, 2]
rf37 = write_result_file(root, res37)
rc, out, err = do_verify("T-930", mid37, hid37, rf37)
chk("a changed_files list of non-strings refuses as malformed", rc == 2 and "malformed result" in err)

# =============================================================================================
t("38. empty changed_files is allowed (a no-op slice can still PASS)")
mid38, hid38 = make_handoff()
res38 = make_result(hid38, mid38, changed_files=[])
rf38 = write_result_file(root, res38)
rc, out, err = do_verify("T-930", mid38, hid38, rf38)
chk("an empty changed_files list does not itself block a PASS",
    rc == 0 and json.loads(out)["classification"] == "PASS")

# =============================================================================================
t("39. verification report includes every required S4 check")
mid39, hid39 = make_handoff()
res39 = make_result(hid39, mid39)
rf39 = write_result_file(root, res39)
do_verify("T-930", mid39, hid39, rf39)
verification = json.loads(mission.verification_path(d, mid39, hid39).read_text())
check_names = {c["check"] for c in verification["checks"]}
chk("verification report checks identity_match", "identity_match" in check_names)
chk("verification report checks result_hash_match", "result_hash_match" in check_names)
chk("verification report checks scope_bounded", "scope_bounded" in check_names)
chk("verification report checks test_evidence_present", "test_evidence_present" in check_names)
chk("verification report checks within_budget", "within_budget" in check_names)
chk("verification report is fully deterministic (no ai/lease/claim booleans all true)",
    verification["no_ai_invoked"] is True and verification["no_lease_or_claim_acquired"] is True
    and verification["no_automatic_approval"] is True and verification["no_automatic_completion"]
    is True and verification["no_continuation_loop"] is True)

# =============================================================================================
t("40. result.json persists the submission verbatim")
mid40, hid40 = make_handoff()
res40 = make_result(hid40, mid40, summary="a very specific summary text")
rf40 = write_result_file(root, res40)
do_verify("T-930", mid40, hid40, rf40)
persisted = json.loads(mission.result_path(d, mid40, hid40).read_text())
chk("the persisted result.json summary matches exactly what was submitted",
    persisted["summary"] == "a very specific summary text")
chk("the persisted result.json status matches exactly what was submitted",
    persisted["status"] == "pass")

# =============================================================================================
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "ATLAS_ADAPTERS", "ATLAS_HANDOFF_TRANSPORTS")}

t("41. all T-051-S1/S2/S3 tests remain green")
r1 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-contract.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-contract.py (T-051-S1) exits 0", r1.returncode == 0)
r2 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-routing.py (T-051-S2) exits 0", r2.returncode == 0)
r3 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-handoff.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-handoff.py (T-051-S3) exits 0", r3.returncode == 0)

t("42. all T-050 tests remain green")
r4 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-conflict-protection.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-conflict-protection.py exits 0", r4.returncode == 0)
r5 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-routing.py exits 0", r5.returncode == 0)
r6 = subprocess.run([sys.executable, str(REPO / "tests" / "test-cli-source-drift.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-cli-source-drift.py exits 0", r6.returncode == 0)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(0 if failed == 0 else 1)
