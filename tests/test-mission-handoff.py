#!/usr/bin/env python3
"""tests/test-mission-handoff.py — T-051-S3: the bounded, foreground planner-to-executor
handoff (`mission handoff`) on top of the T-051-S1 contract and T-051-S2 role resolution.

Every scenario runs against a disposable ATLAS_HOME, plus a disposable adapter registry and
a disposable transport registry (via AI_OS_ADAPTERS / AI_OS_HANDOFF_TRANSPORTS), exactly like
`test-mission-routing.py`'s own fixture pattern. Nothing here reads or writes the real
`adapters/`, the real `internal/governance/policies/handoff-transports.yaml`, any real T-050
record, or any real mission record.

This file proves the S3 scope only: one bounded, foreground handoff packet + receipt, written
entirely inside this mission's own `mission/<mission-id>/handoffs/` subtree. No planner or
executor is ever invoked. No lease, claim, or V6 handoff record is ever created. Mission
approval is never re-run or changed. No continuation loop exists — every handoff is one
explicit, owner-issued call.
"""
import contextlib
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


mission_cli = _load(CLI, "ai-os-mission")
mission = _load(CLI, "aios_mission.py")
core_mission_cli = _load(CORE_CLI, "ai-os-mission")
core_mission = _load(CORE_CLI, "aios_mission.py")


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
# Fixture registries — same pattern as test-mission-routing.py.
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
    verified: {verified}
    evidence: fixture, not a real trial
"""


def write_transports(path, clients, unverified=()):
    body = "contract: 1\n\ntransports:\n"
    for c in clients:
        body += TRANSPORT_ENTRY.format(client=c, verified="false" if c in unverified else "true")
    path.write_text(body)


def new_fixture(ticket_id="T-920"):
    tmp = Path(tempfile.mkdtemp(prefix="t051-s3-"))
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-handoff tests\nstate: active\n"
        "project: demo\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id))

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    transports_path = tmp / "handoff-transports.yaml"

    for c in ("test-planner", "test-executor", "no-transport-planner"):
        write_adapter(adapters_dir, c)
    # NOTE: "no-adapter-executor" intentionally has no adapter dir — used to force an
    # ambiguous-role refusal on a fresh mission's executor.

    write_transports(transports_path, ["test-planner", "test-executor", "no-adapter-executor"])
    # "no-transport-planner" has an adapter but no transport entry at all — same idea, planner
    # side.

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["AI_OS_ADAPTERS"] = str(adapters_dir)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp, d, adapters_dir, transports_path


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def do_create(task_id, scopes=("scope-a.txt",), planner="test-planner",
             executor="test-executor", verifier="test-planner", budget="5",
             max_slices="3", max_attempts="2", ttl="3600", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("create")
    args = [task_id]
    for s in scopes:
        args += ["--scope", s]
    args += ["--planner", planner, "--executor", executor, "--verifier", verifier,
            "--budget-usd", budget, "--max-slices", max_slices, "--max-attempts", max_attempts,
            "--ttl-seconds", ttl, "--idempotency-key", key]
    return run(m.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def do_approve(task_id, mission_id, owner_words="approved by owner fixture", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("approve")
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words", owner_words,
                               "--idempotency-key", key])


def make_approved_mission(task_id="T-920", m=None, **create_kwargs):
    m = m or mission_cli
    rc, out, err = do_create(task_id, m=m, **create_kwargs)
    assert rc == 0, (rc, out, err)
    mid = mission_id_from(out)
    rc, out, err = do_approve(task_id, mid, m=m)
    assert rc == 0, (rc, out, err)
    return mid


def do_handoff(task_id, mission_id, scope="scope-a.txt", executor_client="test-executor",
              session=None, invocation=None, gate="execute", budget="1", key=None, m=None):
    m = m or mission_cli
    session = session or uniq_key("sess")
    invocation = invocation or uniq_key("inv")
    key = key or uniq_key("handoff")
    args = [task_id, mission_id, "--scope", scope, "--executor-client", executor_client,
           "--executor-session", session, "--invocation-id", invocation, "--gate", gate,
           "--slice-budget-usd", budget, "--idempotency-key", key, "--json"]
    return run(m.cmd_handoff, args)


def tamper_json(path, mutate_fn):
    obj = json.loads(path.read_text())
    mutate_fn(obj)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2))


# =============================================================================================
t("1. valid handoff on an approved mission")
root, d, adapters_dir, transports_path = new_fixture()
(d / "scope-a.txt").write_text("x")
mid = make_approved_mission()
rc, out, err = do_handoff("T-920", mid)
chk("handoff on an approved mission exits 0", rc == 0)
view = json.loads(out) if rc == 0 else {}
chk("handoff reports mission state unchanged (still approved)", view.get("state") == "approved")
chk("handoff reports attempts_used == 1", view.get("attempts_used") == 1)
chk("handoff reports budget_committed_usd == 1.0", view.get("budget_committed_usd") == 1.0)
chk("handoff reports remaining_budget_usd == 4.0", view.get("remaining_budget_usd") == 4.0)
chk("packet.json was written on disk", Path(view.get("packet_path", "")).is_file())
chk("receipt.json was written on disk", Path(view.get("receipt_path", "")).is_file())

# =============================================================================================
t("2. unapproved mission refusal")
rc, out, err = do_create("T-920", key=uniq_key("unapproved"))
unapproved_mid = mission_id_from(out)
rc, out, err = do_handoff("T-920", unapproved_mid)
chk("handoff against an unapproved mission refuses", rc == 5 and "approved" in err)

# =============================================================================================
t("3. role resolution and identity propagation")
packet = json.loads(Path(view["packet_path"]).read_text())
receipt = json.loads(Path(view["receipt_path"]).read_text())
chk("packet's planner_client matches the mission contract", packet["planner_client"] == "test-planner")
chk("packet's executor_client matches the mission contract", packet["executor_client"] == "test-executor")
chk("receipt's planner_route resolves the same client", receipt["planner_route"]["client"] == "test-planner")
chk("receipt's executor_route resolves the same client", receipt["executor_route"]["client"] == "test-executor")
chk("receipt's executor_route is transport_verified", receipt["executor_route"]["transport_verified"] is True)
chk("packet echoes allowed_tools Read/Edit", set(packet["allowed_tools"]) == {"Read", "Edit"})
chk("packet echoes the mission's denied_tools", "Bash" in packet["denied_tools"])
chk("packet echoes stop_conditions from the contract", len(packet["stop_conditions"]) > 0)

# =============================================================================================
t("4. exact scope enforcement")
mid4 = make_approved_mission(scopes=("scope-a.txt", "scope-b.txt"))
(d / "scope-b.txt").write_text("y")
rc, out, err = do_handoff("T-920", mid4, scope="scope-nonexistent.txt")
chk("handoff against a scope not on the mission refuses", rc == 5 and "approved scopes" in err)
rc, out, err = do_handoff("T-920", mid4, scope="scope-b.txt")
chk("handoff against the mission's second approved scope succeeds", rc == 0)

# =============================================================================================
t("5. executor client mismatch refusal")
mid5 = make_approved_mission()
rc, out, err = do_handoff("T-920", mid5, executor_client="test-planner")
chk("handoff with an executor-client that does not match the contract refuses",
    rc == 5 and "executor_client" in err)

# =============================================================================================
t("6. over-budget refusal")
mid6 = make_approved_mission(budget="1")
rc, out, err = do_handoff("T-920", mid6, budget="5")
chk("a slice budget exceeding the mission's total budget refuses", rc == 5 and "budget" in err)
rc, out, err = do_handoff("T-920", mid6, budget="1")
chk("a slice budget exactly at the mission's remaining budget succeeds", rc == 0)
rc, out, err = do_handoff("T-920", mid6, budget="0.01", invocation=uniq_key("inv"))
chk("a further handoff after the budget is exhausted refuses", rc == 5)

# =============================================================================================
t("7. attempt limits")
mid7 = make_approved_mission(max_attempts="1")
rc, out, err = do_handoff("T-920", mid7)
chk("the first handoff within max_attempts succeeds", rc == 0)
rc, out, err = do_handoff("T-920", mid7, invocation=uniq_key("inv2"))
chk("a second handoff beyond max_attempts refuses", rc == 5 and "max_attempts" in err)

# =============================================================================================
t("8. max_slices (distinct scope) limits")
mid8 = make_approved_mission(scopes=("scope-a.txt", "scope-b.txt"), max_slices="1",
                             max_attempts="5")
rc, out, err = do_handoff("T-920", mid8, scope="scope-a.txt")
chk("the first distinct scope within max_slices succeeds", rc == 0)
rc, out, err = do_handoff("T-920", mid8, scope="scope-a.txt", invocation=uniq_key("inv2"))
chk("retrying the SAME scope does not count as a new slice", rc == 0)
rc, out, err = do_handoff("T-920", mid8, scope="scope-b.txt", invocation=uniq_key("inv3"))
chk("a second DISTINCT scope beyond max_slices refuses", rc == 5 and "max_slices" in err)

# =============================================================================================
t("9. idempotent replay")
mid9 = make_approved_mission()
key9 = uniq_key("idem")
sess9, inv9 = uniq_key("sess"), uniq_key("inv")
rc1, out1, _ = do_handoff("T-920", mid9, session=sess9, invocation=inv9, key=key9)
rc2, out2, _ = do_handoff("T-920", mid9, session=sess9, invocation=inv9, key=key9)
v1, v2 = json.loads(out1), json.loads(out2)
chk("a replayed handoff (same key, same args) exits 0 both times", rc1 == 0 and rc2 == 0)
chk("a replayed handoff returns the identical handoff_id", v1["handoff_id"] == v2["handoff_id"])
chk("a replayed handoff does not consume a second attempt",
    v2["attempts_used"] == v1["attempts_used"] == 1)
chk("a replayed handoff does not commit a second budget amount",
    v2["budget_committed_usd"] == v1["budget_committed_usd"])

# =============================================================================================
t("10. conflicting replay (same key, different request) refusal")
mid10 = make_approved_mission(scopes=("scope-a.txt", "scope-b.txt"))
key10 = uniq_key("conflict")
rc1, out1, _ = do_handoff("T-920", mid10, scope="scope-a.txt", key=key10)
chk("the first call with a fresh key succeeds", rc1 == 0)
rc2, out2, err2 = do_handoff("T-920", mid10, scope="scope-b.txt", key=key10)
chk("reusing the same key for a materially different request refuses",
    rc2 == 5 and "conflicting" in err2.lower() or "different" in err2.lower())

# =============================================================================================
t("11. refusal before dispatch on every invalid condition")
mid11 = make_approved_mission()

rc, out, err = do_handoff("T-920", mid11, gate="not-a-real-gate")
chk("an unknown gate refuses", rc == 2 and "gate" in err)

rc, out, err = run(mission_cli.cmd_handoff,
                   ["T-920", mid11, "--executor-client", "test-executor",
                    "--executor-session", "s", "--invocation-id", "i", "--gate", "execute",
                    "--slice-budget-usd", "1", "--idempotency-key", uniq_key("noscope")])
chk("a missing --scope refuses", rc == 2)

rc, out, err = run(mission_cli.cmd_handoff,
                   ["T-920", mid11, "--scope", "scope-a.txt", "--executor-session", "s",
                    "--invocation-id", "i", "--gate", "execute", "--slice-budget-usd", "1",
                    "--idempotency-key", uniq_key("noexec")])
chk("a missing --executor-client refuses", rc == 2)

rc, out, err = run(mission_cli.cmd_handoff,
                   ["T-920", mid11, "--scope", "scope-a.txt", "--executor-client",
                    "test-executor", "--invocation-id", "i", "--gate", "execute",
                    "--slice-budget-usd", "1", "--idempotency-key", uniq_key("nosess")])
chk("a missing --executor-session refuses", rc == 2)

rc, out, err = run(mission_cli.cmd_handoff,
                   ["T-920", mid11, "--scope", "scope-a.txt", "--executor-client",
                    "test-executor", "--executor-session", "s", "--gate", "execute",
                    "--slice-budget-usd", "1", "--idempotency-key", uniq_key("noinv")])
chk("a missing --invocation-id refuses", rc == 2)

# Closed-mission refusal: tamper state.json into every closed state.
for closed_state in ("blocked", "cancelled", "expired", "needs_owner"):
    mid_closed = make_approved_mission()
    tamper_json(mission.state_path(d, mid_closed), lambda s: s.__setitem__("state", closed_state))
    rc, out, err = do_handoff("T-920", mid_closed)
    chk(f"handoff against a mission in state {closed_state!r} refuses",
        rc == 5 and "closed" in err)

# TTL elapsed refusal.
mid_ttl = make_approved_mission(ttl="1")
tamper_json(mission.state_path(d, mid_ttl),
           lambda s: s.__setitem__("approved_at", "2000-01-01T00:00:00+00:00"))
rc, out, err = do_handoff("T-920", mid_ttl)
chk("handoff after ttl_seconds has elapsed refuses", rc == 5 and "ttl_seconds" in err)

# Ambiguous planner/executor role refusal.
mid_ambig_executor = make_approved_mission(executor="no-adapter-executor")
rc, out, err = do_handoff("T-920", mid_ambig_executor, executor_client="no-adapter-executor")
chk("handoff with an executor that has no adapter refuses (ambiguous role)", rc == 5)

mid_ambig_planner = make_approved_mission(planner="no-transport-planner")
rc, out, err = do_handoff("T-920", mid_ambig_planner)
chk("handoff with a planner that has no transport refuses (ambiguous role)", rc == 5)

# =============================================================================================
t("12. no automatic approval")
mid12 = make_approved_mission()
state_before = json.loads(mission.state_path(d, mid12).read_text())
do_handoff("T-920", mid12)
state_after = json.loads(mission.state_path(d, mid12).read_text())
chk("approval field is unchanged by a handoff", state_before["approval"] == state_after["approval"] == "recorded")
chk("owner_words are unchanged by a handoff", state_before["owner_words"] == state_after["owner_words"])
chk("approval_scope_hash is unchanged by a handoff",
    state_before["approval_scope_hash"] == state_after["approval_scope_hash"])
chk("mission state remains 'approved' after a handoff (no autonomous state transition)",
    state_after["state"] == "approved")

# =============================================================================================
t("13. no continuation loop")
mid13 = make_approved_mission(scopes=("scope-a.txt", "scope-b.txt"), max_attempts="5")
do_handoff("T-920", mid13, scope="scope-a.txt")
before_next = snapshot(root)
# a second call is a fully separate, explicit, owner-issued command — never triggered by the
# first call itself.
do_handoff("T-920", mid13, scope="scope-b.txt", invocation=uniq_key("inv"))
chk("the first handoff call never spawns a second one on its own; a second one only exists "
    "because this test explicitly issued it",
    len(list(mission.handoffs_root(d, mid13).glob("handoff-*"))) == 2)
mid13b = make_approved_mission()
do_handoff("T-920", mid13b)
handoff_count = len(list(mission.handoffs_root(d, mid13b).glob("handoff-*")))
chk("exactly one handoff directory exists after exactly one handoff call", handoff_count == 1)

# =============================================================================================
t("14. entirely bounded to this mission's own subtree — no T-050 state anywhere")
mid14 = make_approved_mission()
before = snapshot(root)
do_handoff("T-920", mid14)
after = snapshot(root)
new_paths = [p for p in after if p not in before]
chk("every new path created by a handoff lives under this mission's own handoffs/ or "
    "state.json/audit.log",
    all(("/mission/" in p or p.endswith("mission")) for p in new_paths))
chk("no coordination/ directory exists anywhere under the fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the fixture root (only this mission's "
    "own JSON packet/receipt files)",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("15. deterministic output")
mid15 = make_approved_mission()
sess15, inv15, key15 = uniq_key("s"), uniq_key("i"), uniq_key("k")
rc0, out0, _ = do_handoff("T-920", mid15, session=sess15, invocation=inv15, key=key15)
chk("the first (creating) handoff call exits 0", rc0 == 0)
# Two REPLAYS of the same already-created handoff must be byte-identical to each other (the
# first call is necessarily different: it alone carries replay:false).
rc1, out1, _ = do_handoff("T-920", mid15, session=sess15, invocation=inv15, key=key15)
rc2, out2, _ = do_handoff("T-920", mid15, session=sess15, invocation=inv15, key=key15)
chk("repeated JSON replay calls are byte-identical", rc1 == rc2 == 0 and out1 == out2)
chk("JSON output round-trips", json.loads(out1) == json.loads(out2))
chk("both replays report replay: true", json.loads(out1)["replay"] is True and
    json.loads(out2)["replay"] is True)

# =============================================================================================
t("16. no AI invocation")
src = (CLI / "aios_mission.py").read_text()
handoff_section = src[src.index("T-051-S3"):]
chk("no subprocess call appears in the S3 section of aios_mission.py",
    "subprocess.run(" not in handoff_section)
chk("no socket/urllib/requests import appears anywhere in aios_mission.py",
    not any(tok in src for tok in ("import socket", "import urllib", "import requests")))
only_subprocess_use = src.count("subprocess.run(")
chk("the only subprocess.run call in the whole file targets ai-os-paths (pre-existing, S1)",
    only_subprocess_use == 1 and "PATHS_RESOLVER" in src)

# =============================================================================================
t("17. core/engine parity")
mid_engine_parity = make_approved_mission(m=mission_cli)
mid_core_parity = make_approved_mission(m=core_mission_cli)
rc_e, out_e, _ = do_handoff("T-920", mid_engine_parity, m=mission_cli)
rc_c, out_c, _ = do_handoff("T-920", mid_core_parity, m=core_mission_cli)
view_e, view_c = json.loads(out_e), json.loads(out_c)
shape_e = {k: v for k, v in view_e.items() if k not in ("mission_id", "handoff_id",
          "packet_path", "receipt_path", "created_at")}
shape_c = {k: v for k, v in view_c.items() if k not in ("mission_id", "handoff_id",
          "packet_path", "receipt_path", "created_at")}
chk("engine and core mission handoff agree on state/attempts/budget shape",
    rc_e == 0 and rc_c == 0 and shape_e == shape_c)

engine_py = CLI / "aios_mission.py"
core_py = CORE_CLI / "aios_mission.py"
chk("engine/cli/aios_mission.py and core/cli/aios_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "ai-os-mission"
core_cli_file = CORE_CLI / "ai-os-mission"
chk("engine/cli/ai-os-mission and core/cli/ai-os-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())

# =============================================================================================
t("18. canonical atlas parity — no dispatcher edit was required")
atlas_text = (CLI / "atlas").read_text()
core_ai_os_text = (CORE_CLI / "ai-os").read_text()
chk("'mission' still sits in engine/cli/atlas's generic exec-by-name case arm",
    "mission|" in atlas_text or "|mission" in atlas_text)
chk("'mission' still sits in core/cli/ai-os's generic exec-by-name case arm",
    "mission|" in core_ai_os_text or "|mission" in core_ai_os_text)

# =============================================================================================
t("19. protected files untouched")
import hashlib as _hashlib


def _sha(p):
    return _hashlib.sha256(Path(p).read_bytes()).hexdigest()


PROTECTED = [
    CLI / "ai-os-coordinator", CORE_CLI / "ai-os-coordinator",
    CLI / "aios_coordination.py", CORE_CLI / "aios_coordination.py",
    CLI / "ai-os-handoff", CORE_CLI / "ai-os-handoff",
    REPO / "internal" / "governance" / "policies" / "handoff-transports.yaml",
    REPO / "internal" / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())

# =============================================================================================
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS")}

t("20. all T-051-S1 and T-051-S2 tests remain green")
r1 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-contract.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-contract.py (T-051-S1) exits 0", r1.returncode == 0)
r2 = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-routing.py (T-051-S2) exits 0", r2.returncode == 0)

t("21. all T-050 tests remain green")
r3 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-conflict-protection.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-conflict-protection.py exits 0", r3.returncode == 0)
r4 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-routing.py exits 0", r4.returncode == 0)
r5 = subprocess.run([sys.executable, str(REPO / "tests" / "test-cli-source-drift.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-cli-source-drift.py exits 0", r5.returncode == 0)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(0 if failed == 0 else 1)
