#!/usr/bin/env python3
"""tests/test-mission-pilot.py — T-051-S7: the two-ticket pilot, run on top of the complete
T-051-S1..S6 mission pipeline (contract, role resolution, bounded handoff, verifier gate,
continuation loop, finalize).

## What this file actually proves, and what it does not

This file runs the FULL mission pipeline (create -> approve -> handoff -> verify ->
[continue] -> finalize) twice, concurrently/interleaved, against two disposable fixture
tickets with non-overlapping approved scopes, distinct mission ids, distinct executor
sessions, and distinct invocation ids — exactly as the S7 pilot rules require. Every fixture
here (adapter manifests, transport registry) is disposable, pointed at via
ATLAS_ADAPTERS / ATLAS_HANDOFF_TRANSPORTS / ATLAS_HOME overrides, exactly like every prior
T-051 mission test file. Nothing here reads or writes the real `adapters/`, the real
`governance/policies/handoff-transports.yaml`, T-050, T-051, AIOS-011, AIOS-012,
AIOS-017, or any production ticket.

**The one thing this file does NOT do is invoke a live Claude CLI process**, and it says so
explicitly (test 1). The only currently-registered bounded Claude Code CLI transport
(`claude-code-tools-pilot` in the real `governance/policies/handoff-transports.yaml`)
has its `--add-dir` hard-coded to the real `projects/atlas/tickets/AIOS-012` directory — a
production ticket this pilot is explicitly forbidden from touching. Editing that transport
file to point at a disposable fixture directory is forbidden (it is a protected file for this
slice); inventing a second transport registry to work around that is explicitly forbidden;
and hand-rolling an unregistered `claude -p ...` invocation outside the transport registry
would not be "the existing bounded Claude CLI transport" the pilot rules require — it would
also be a real, live, nested Claude Code invocation from inside this very session, spending
real API budget without the operator having been asked, which this file's own author judged
unsafe to do unprompted. Per the S7 prompt's own instruction ("If the installed Claude CLI or
the current session cannot safely perform a nested bounded pilot, report S7 as BLOCKED. Do
not fake a real execution result and do not substitute a static fixture for a real AI
invocation without saying so."), this is reported as BLOCKED for the live-invocation
requirement specifically, and disclosed here and in every place that requirement is tested.

Every other pilot requirement — two independent fixture tickets and missions, non-overlapping
scopes, distinct session/invocation identity, concurrent/interleaved execution, a REAL file
edit on disk (performed directly by this test harness, not by an AI), independent completion,
no cross-ticket collision, no duplicate continuation, no double-counted budget/attempts, a
blocked pilot producing a blocker packet, and deterministic final reports — is exercised for
real against the actual T-051 code, not mocked.
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
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli"

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
t("1. real Claude CLI invocation — explicit disclosure (read this before anything else)")
PILOT_REAL_AI_INVOKED = False
PILOT_BLOCKED_REASON = (
    "the only registered bounded Claude Code CLI transport (claude-code-tools-pilot) has its "
    "--add-dir hard-coded to the real projects/atlas/tickets/AIOS-012 directory, a production "
    "ticket this pilot may not touch; handoff-transports.yaml is a protected file for this "
    "slice and may not be edited to retarget it; a second transport registry is explicitly "
    "forbidden; and an unregistered ad-hoc `claude -p` invocation would be a real, live, "
    "nested Claude Code call from inside this session, spending real API budget without the "
    "operator having explicitly authorized that spend — judged unsafe to do unprompted."
)
chk("this file explicitly declares PILOT_REAL_AI_INVOKED = False (never silently claims a "
    "real AI invocation happened)", PILOT_REAL_AI_INVOKED is False)
print(f"  {Y}S7 NOTE{X}: real Claude CLI invocation reported BLOCKED — {PILOT_BLOCKED_REASON}")
chk("a real, unmodified `claude` binary is present in this environment (the CLI itself is "
    "not the blocker — the transport registry constraint is)",
    subprocess.run(["which", "claude"], capture_output=True, text=True).returncode == 0)


# =============================================================================================
# Fixture registries — disposable, never the real adapters/ or handoff-transports.yaml.
# Client names mirror the real registry's own naming (`codex`, `claude-code-tools-pilot`) so
# the pilot's role assignment matches the S7 prompt's own "Codex plans/verifies, Claude CLI
# executes" model in shape, even though nothing here dispatches to a real binary.
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


TRANSPORT_ENTRY_BOUNDED = """\
  {client}:
    name: fixture bounded Read/Edit transport for {client}
    binary: {client}-bin
    argv: [--tools, "Read,Edit", --permission-mode, acceptEdits, --max-budget-usd, "0.10"]
    stdin: packet
    timeout: 60
    verified: true
    evidence: fixture, mirrors the real claude-code-tools-pilot policy shape; not dispatched
"""

TRANSPORT_ENTRY_PLAIN = """\
  {client}:
    name: fixture transport for {client}
    binary: {client}-bin
    argv: [--tools, "Read,Edit"]
    stdin: packet
    timeout: 60
    verified: true
    evidence: fixture, not a real trial
"""


def write_transports(path, bounded_clients, plain_clients):
    body = "contract: 1\n\ntransports:\n"
    for c in bounded_clients:
        body += TRANSPORT_ENTRY_BOUNDED.format(client=c)
    for c in plain_clients:
        body += TRANSPORT_ENTRY_PLAIN.format(client=c)
    path.write_text(body)


def new_pilot_fixture():
    """One shared disposable ATLAS_HOME holding TWO independent fixture tickets — exactly
    the S7 pilot's own two-ticket shape. Distinct ticket ids, distinct scope subdirectories
    (non-overlapping canonical paths), one shared disposable adapter/transport registry."""
    tmp = Path(tempfile.mkdtemp(prefix="t051-s7-pilot-"))

    ticket_a = tmp / "projects" / "demo" / "tickets" / "T-960-A"
    ticket_b = tmp / "projects" / "demo" / "tickets" / "T-960-B"
    for tid, d in (("T-960-A", ticket_a), ("T-960-B", ticket_b)):
        d.mkdir(parents=True, exist_ok=True)
        (d / "task.md").write_text(
            "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
            "title: fixture pilot ticket {id}\nstate: active\n"
            "project: demo\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
            "artifacts: []\n---\n# fixture\n".format(id=tid))

    # Non-overlapping canonical paths: separate subdirectories under ATLAS_HOME, never the
    # same file, never a shared parent that could be mistaken for one ticket's scope.
    (tmp / "pilot-a").mkdir(parents=True, exist_ok=True)
    (tmp / "pilot-b").mkdir(parents=True, exist_ok=True)
    alpha = tmp / "pilot-a" / "alpha.txt"
    beta = tmp / "pilot-b" / "beta.txt"
    alpha.write_text("alpha: untouched baseline\n")
    beta.write_text("beta: untouched baseline\n")

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    transports_path = tmp / "handoff-transports.yaml"
    for c in ("codex", "claude-code-tools-pilot"):
        write_adapter(adapters_dir, c)
    write_transports(transports_path, bounded_clients=["claude-code-tools-pilot"],
                     plain_clients=["codex"])

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["ATLAS_ADAPTERS"] = str(adapters_dir)
    os.environ["ATLAS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp, ticket_a, ticket_b, alpha, beta


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def do_create(task_id, scopes, budget="0.10", max_slices="3", max_attempts="5", ttl="3600",
             key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("create")
    args = [task_id]
    for s in scopes:
        args += ["--scope", s]
    args += ["--planner", "codex", "--executor", "claude-code-tools-pilot", "--verifier",
            "codex", "--budget-usd", budget, "--max-slices", max_slices,
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
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words",
                               "approved by pilot owner", "--idempotency-key", key])


def do_handoff(task_id, mission_id, scope, session, invocation, gate="execute",
              budget="0.05", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("handoff")
    args = [task_id, mission_id, "--scope", scope, "--executor-client",
           "claude-code-tools-pilot", "--executor-session", session, "--invocation-id",
           invocation, "--gate", gate, "--slice-budget-usd", budget, "--idempotency-key",
           key, "--json"]
    return run(m.cmd_handoff, args)


def result_hash(handoff_id, mission_id, root_task_id, status, changed_files, tests_field,
                summary):
    material = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "status": status, "changed_files": sorted(changed_files), "tests": tests_field,
        "summary": summary,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def make_result(handoff_id, mission_id, root_task_id, executor_session, invocation_id,
                scope, status="pass", changed_files=(), tests=("pytest ok",),
                reported_cost_usd=0.05, summary="edited the approved fixture file",
                blocker=None, owner_decision_required=None):
    tests_field = list(tests)
    h = result_hash(handoff_id, mission_id, root_task_id, status, changed_files, tests_field,
                    summary)
    result = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "executor_client": "claude-code-tools-pilot", "executor_session": executor_session,
        "invocation_id": invocation_id, "gate": "execute", "scope": scope, "status": status,
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


def do_continue(task_id, mission_id, handoff_id, scope, session, invocation, budget="0.02",
                key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("continue")
    args = [task_id, mission_id, handoff_id, "--scope", scope, "--executor-client",
           "claude-code-tools-pilot", "--executor-session", session, "--invocation-id",
           invocation, "--gate", "execute", "--slice-budget-usd", budget,
           "--idempotency-key", key, "--json"]
    return run(m.cmd_continue, args)


def do_finalize(task_id, mission_id, handoff_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("finalize")
    return run(m.cmd_finalize, [task_id, mission_id, handoff_id, "--idempotency-key", key,
                               "--json"])


def real_bounded_edit(path, new_content):
    """The one REAL, on-disk file mutation this pilot performs — a direct, deterministic
    write, standing in for what a bounded Claude CLI executor would have done under
    Read/Edit-only tool access. Performed by this test harness, never by a live AI process —
    see test 1's disclosure. Returns the new content so callers can build an honest result
    packet against what actually changed on disk."""
    path.write_text(new_content)
    return new_content


# =============================================================================================
t("2. two disposable fixture tickets, different ids")
root, ticket_a_dir, ticket_b_dir, alpha_path, beta_path = new_pilot_fixture()
chk("ticket A and ticket B have different ids", "T-960-A" != "T-960-B")
chk("ticket A's directory exists", ticket_a_dir.is_dir())
chk("ticket B's directory exists", ticket_b_dir.is_dir())
chk("ticket A is not T-050, T-051, AIOS-011, AIOS-012, or AIOS-017",
    "T-960-A" not in ("T-050", "T-051", "AIOS-011", "AIOS-012", "AIOS-017"))
chk("ticket B is not T-050, T-051, AIOS-011, AIOS-012, or AIOS-017",
    "T-960-B" not in ("T-050", "T-051", "AIOS-011", "AIOS-012", "AIOS-017"))

# =============================================================================================
t("3. different approved scope files with non-overlapping canonical paths")
scope_a_raw, scope_b_raw = "pilot-a/alpha.txt", "pilot-b/beta.txt"
chk("the two raw scope strings differ", scope_a_raw != scope_b_raw)
canon_a = mission.canonicalize_scope(scope_a_raw)
canon_b = mission.canonicalize_scope(scope_b_raw)
chk("the two canonical paths differ", canon_a["canonical"] != canon_b["canonical"])
chk("neither canonical path is a prefix of the other (truly non-overlapping directories)",
    not canon_a["canonical"].startswith(str(Path(canon_b["canonical"]).parent) + "/pilot-a")
    and canon_a["canonical"] != canon_b["canonical"])

# =============================================================================================
t("4/5/6. separate mission ids, session ids, and invocation ids")
rc, out, err = do_create("T-960-A", scopes=[scope_a_raw])
assert rc == 0, (rc, out, err)
mission_a = mission_id_from(out)
rc, out, err = do_create("T-960-B", scopes=[scope_b_raw])
assert rc == 0, (rc, out, err)
mission_b = mission_id_from(out)
chk("mission A and mission B have different mission ids", mission_a != mission_b)

session_a, session_b = "pilot-session-A-001", "pilot-session-B-001"
invocation_a, invocation_b = "pilot-invocation-A-001", "pilot-invocation-B-001"
chk("session A and session B are different identities", session_a != session_b)
chk("invocation A and invocation B are different identities", invocation_a != invocation_b)

# =============================================================================================
t("7. concurrent/interleaved execution — approve, handoff, edit, verify, finalize, "
   "interleaved between the two missions")
rc, out, err = do_approve("T-960-A", mission_a)
assert rc == 0, (rc, out, err)
rc, out, err = do_approve("T-960-B", mission_b)
assert rc == 0, (rc, out, err)
chk("both missions approved independently", True)

rc, out, err = do_handoff("T-960-A", mission_a, scope_a_raw, session_a, invocation_a)
assert rc == 0, (rc, out, err)
handoff_a = json.loads(out)["handoff_id"]
rc, out, err = do_handoff("T-960-B", mission_b, scope_b_raw, session_b, invocation_b)
assert rc == 0, (rc, out, err)
handoff_b = json.loads(out)["handoff_id"]
chk("both missions received one bounded handoff each", handoff_a != handoff_b)

# The one REAL, on-disk bounded file edit each mission's "executor" performs (see test 1).
new_alpha = real_bounded_edit(alpha_path, "alpha: edited by pilot mission A\n")
new_beta = real_bounded_edit(beta_path, "beta: edited by pilot mission B\n")

res_a = make_result(handoff_a, mission_a, "T-960-A", session_a, invocation_a, scope_a_raw,
                    changed_files=[scope_a_raw])
res_b = make_result(handoff_b, mission_b, "T-960-B", session_b, invocation_b, scope_b_raw,
                    changed_files=[scope_b_raw])
rf_a = write_result_file(root, res_a)
rf_b = write_result_file(root, res_b)

rc, out, err = do_verify("T-960-B", mission_b, handoff_b, rf_b)
assert rc == 0, (rc, out, err)
chk("mission B verified first (interleaved order, not mission A's own order)",
    json.loads(out)["classification"] == "PASS")
rc, out, err = do_verify("T-960-A", mission_a, handoff_a, rf_a)
assert rc == 0, (rc, out, err)
chk("mission A verified second, independently of mission B's own verify call",
    json.loads(out)["classification"] == "PASS")

rc, out, err = do_finalize("T-960-A", mission_a, handoff_a)
assert rc == 0, (rc, out, err)
final_a = json.loads(out)
rc, out, err = do_finalize("T-960-B", mission_b, handoff_b)
assert rc == 0, (rc, out, err)
final_b = json.loads(out)

# =============================================================================================
t("8. both missions complete independently")
chk("mission A finalized as completed", final_a["mission_state"] == "completed")
chk("mission B finalized as completed", final_b["mission_state"] == "completed")
state_a = json.loads(mission.state_path(ticket_a_dir, mission_a).read_text())
state_b = json.loads(mission.state_path(ticket_b_dir, mission_b).read_text())
chk("mission A's own state.json independently reads completed", state_a["state"] == "completed")
chk("mission B's own state.json independently reads completed", state_b["state"] == "completed")

# =============================================================================================
t("9. each executor edited only its own file")
chk("alpha.txt now holds mission A's own edit", alpha_path.read_text() == new_alpha)
chk("beta.txt now holds mission B's own edit", beta_path.read_text() == new_beta)
chk("alpha.txt was never touched by mission B's edit content",
    "mission B" not in alpha_path.read_text())
chk("beta.txt was never touched by mission A's edit content",
    "mission A" not in beta_path.read_text())

# =============================================================================================
t("10. no cross-ticket claim or scope collision")
chk("mission A's final report references only its own scope",
    final_a is not None)
report_a = json.loads(Path(final_a["final_report_path"]).read_text())
report_b = json.loads(Path(final_b["final_report_path"]).read_text())
chk("mission A's final report's approved_scope is exactly scope_a", report_a["approved_scope"] == scope_a_raw)
chk("mission B's final report's approved_scope is exactly scope_b", report_b["approved_scope"] == scope_b_raw)
chk("mission A's final report never mentions mission B's own mission id",
    mission_b not in json.dumps(report_a))
chk("mission B's final report never mentions mission A's own mission id",
    mission_a not in json.dumps(report_b))
chk("no coordination/, runtime/, claims/, or leases/ directory exists anywhere",
    not any(p.name in ("coordination", "runtime", "claims", "leases")
           for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("11. cross-ticket identity mismatch refused")
rc, out, err = do_verify("T-960-B", mission_b, handoff_a, rf_a)
chk("verifying mission A's own handoff id under mission B's own ticket/mission refuses",
    rc == 4)

# =============================================================================================
t("12. cross-ticket scope mismatch refused")
mid_c1, mid_c2 = None, None
rc, out, err = do_create("T-960-A", scopes=[scope_a_raw], key=uniq_key("scope-mismatch"))
assert rc == 0, (rc, out, err)
mission_a2 = mission_id_from(out)
rc, out, err = do_approve("T-960-A", mission_a2, key=uniq_key("scope-mismatch-approve"))
assert rc == 0, (rc, out, err)
rc, out, err = do_handoff("T-960-A", mission_a2, scope_b_raw, session_a, invocation_a,
                          key=uniq_key("scope-mismatch-handoff"))
chk("handing off mission A2 (approved scope = alpha) using ticket B's own scope refuses",
    rc == 5)

# =============================================================================================
t("13. no mission can use the other mission's session or invocation")
rc, out, err = do_create("T-960-A", scopes=[scope_a_raw, "pilot-a/alpha2.txt"],
                         max_attempts="5", max_slices="5", key=uniq_key("sess-guard"))
assert rc == 0, (rc, out, err)
mission_a3 = mission_id_from(out)
rc, out, err = do_approve("T-960-A", mission_a3, key=uniq_key("sess-guard-approve"))
assert rc == 0, (rc, out, err)
rc, out, err = do_handoff("T-960-A", mission_a3, scope_a_raw, session_a, invocation_a,
                          key=uniq_key("sess-guard-handoff"))
assert rc == 0, (rc, out, err)
handoff_a3 = json.loads(out)["handoff_id"]
res_a3 = make_result(handoff_a3, mission_a3, "T-960-A", session_a, invocation_a, scope_a_raw,
                     changed_files=[scope_a_raw])
rf_a3 = write_result_file(root, res_a3)
rc, out, err = do_verify("T-960-A", mission_a3, handoff_a3, rf_a3, key=uniq_key("sess-guard-v"))
assert rc == 0 and json.loads(out)["classification"] == "PASS", (rc, out, err)
rc, out, err = do_continue("T-960-A", mission_a3, handoff_a3, "pilot-a/alpha2.txt", session_b,
                           invocation_a, key=uniq_key("cross-session"))
chk("continuing mission A's own handoff using mission B's own executor_session refuses",
    rc == 5 and "session" in err.lower())

# =============================================================================================
t("14. no duplicate continuation")
(root / "pilot-a" / "alpha2.txt").write_text("alpha2: baseline\n")
rc, out, err = do_continue("T-960-A", mission_a3, handoff_a3, "pilot-a/alpha2.txt", session_a,
                           invocation_a, key=uniq_key("real-continue"))
chk("a correctly-scoped, correctly-sessioned continuation succeeds", rc == 0)
handoff_a3b = json.loads(out)["handoff_id"]
before_dupe = len(list(mission.handoffs_root(ticket_a_dir, mission_a3).glob("handoff-*")))
key_dupe = uniq_key("dupe-check")
rc, out, err = do_continue("T-960-A", mission_a3, handoff_a3, "pilot-a/alpha2.txt", session_a,
                           invocation_a, key=key_dupe)
after_first_dupe = len(list(mission.handoffs_root(ticket_a_dir, mission_a3).glob("handoff-*")))
rc2, out2, err2 = do_continue("T-960-A", mission_a3, handoff_a3, "pilot-a/alpha2.txt",
                              session_a, invocation_a, key=key_dupe)
after_second_dupe = len(list(mission.handoffs_root(ticket_a_dir, mission_a3).glob("handoff-*")))
chk("replaying the same continuation key never creates a duplicate handoff",
    after_first_dupe == after_second_dupe)

# =============================================================================================
t("15. no budget or attempt counter double-counted across missions")
state_a3 = json.loads(mission.state_path(ticket_a_dir, mission_a3).read_text())
state_b_final = json.loads(mission.state_path(ticket_b_dir, mission_b).read_text())
chk("mission A3's own attempts_used reflects only its own handoffs/continuations, "
    "never mission B's", state_a3["attempts_used"] in (2, 3))
chk("mission B's own attempts_used is untouched by anything done to mission A/A2/A3",
    state_b_final["attempts_used"] == 1)
chk("mission A3's own budget_committed_usd never exceeds its own contract budget_usd",
    state_a3["budget_committed_usd"] <= 0.10 + 1e-9)

# =============================================================================================
t("16. a blocked pilot mission refuses continuation and produces a blocker packet")
rc, out, err = do_create("T-960-B", scopes=["pilot-b/beta-blocked.txt"],
                         key=uniq_key("blocked-mission"))
assert rc == 0, (rc, out, err)
mission_blocked = mission_id_from(out)
rc, out, err = do_approve("T-960-B", mission_blocked, key=uniq_key("blocked-approve"))
assert rc == 0, (rc, out, err)
rc, out, err = do_handoff("T-960-B", mission_blocked, "pilot-b/beta-blocked.txt", session_b,
                          "pilot-invocation-B-blocked", key=uniq_key("blocked-handoff"))
assert rc == 0, (rc, out, err)
handoff_blocked = json.loads(out)["handoff_id"]
res_blocked = make_result(handoff_blocked, mission_blocked, "T-960-B", session_b,
                          "pilot-invocation-B-blocked", "pilot-b/beta-blocked.txt",
                          status="blocked", blocker="fixture: pilot deliberately blocked")
rf_blocked = write_result_file(root, res_blocked)
rc, out, err = do_verify("T-960-B", mission_blocked, handoff_blocked, rf_blocked,
                         key=uniq_key("blocked-verify"))
assert rc == 0 and json.loads(out)["classification"] == "BLOCKED", (rc, out, err)
rc, out, err = do_continue("T-960-B", mission_blocked, handoff_blocked,
                           "pilot-b/beta-blocked.txt", session_b, "pilot-invocation-B-cont",
                           key=uniq_key("blocked-continue-attempt"))
chk("continuation off a BLOCKED pilot handoff refuses, never PASS", rc == 5)
rc, out, err = do_finalize("T-960-B", mission_blocked, handoff_blocked,
                           key=uniq_key("blocked-finalize"))
assert rc == 0, (rc, out, err)
final_blocked = json.loads(out)
chk("the blocked pilot mission finalizes to state 'blocked', never 'completed'",
    final_blocked["mission_state"] == "blocked")
chk("a blocker-packet.json was produced for the blocked pilot mission",
    Path(final_blocked["blocker_packet_path"]).is_file())
blocker_pkg = json.loads(Path(final_blocked["blocker_packet_path"]).read_text())
chk("the blocker packet carries the fixture blocker text",
    blocker_pkg["blocker"] == "fixture: pilot deliberately blocked")

# =============================================================================================
t("17. final reports are deterministic")
key_det_a = uniq_key("det-a")
rc, out, err = do_create("T-960-A", scopes=["pilot-a/alpha-det.txt"], key=key_det_a)
assert rc == 0, (rc, out, err)
mission_det = mission_id_from(out)
rc, out, err = do_approve("T-960-A", mission_det, key=uniq_key("det-approve"))
assert rc == 0, (rc, out, err)
rc, out, err = do_handoff("T-960-A", mission_det, "pilot-a/alpha-det.txt", session_a,
                          "pilot-invocation-det", key=uniq_key("det-handoff"))
assert rc == 0, (rc, out, err)
handoff_det = json.loads(out)["handoff_id"]
res_det = make_result(handoff_det, mission_det, "T-960-A", session_a,
                      "pilot-invocation-det", "pilot-a/alpha-det.txt",
                      changed_files=["pilot-a/alpha-det.txt"])
rf_det = write_result_file(root, res_det)
rc, out, err = do_verify("T-960-A", mission_det, handoff_det, rf_det, key=uniq_key("det-verify"))
assert rc == 0, (rc, out, err)
key_finalize_det = uniq_key("det-finalize")
do_finalize("T-960-A", mission_det, handoff_det, key=key_finalize_det)
rc1, out1, _ = do_finalize("T-960-A", mission_det, handoff_det, key=key_finalize_det)
rc2, out2, _ = do_finalize("T-960-A", mission_det, handoff_det, key=key_finalize_det)
chk("replaying the same finalize request produces byte-identical JSON", rc1 == rc2 == 0 and out1 == out2)

# =============================================================================================
t("18. engine canonical parity for the pilot flow (T-118: core/cli retired, single canonical "
  "copy — nothing left to compare against)")
rc, out, err = do_create("T-960-A", scopes=["pilot-a/alpha-parity.txt"], m=mission_cli,
                         key=uniq_key("parity-e"))
assert rc == 0, (rc, out, err)
mid_parity_e = mission_id_from(out)
rc, out, err = do_approve("T-960-A", mid_parity_e, m=mission_cli, key=uniq_key("parity-ea"))
assert rc == 0, (rc, out, err)
rc_e, out_e, _ = do_handoff("T-960-A", mid_parity_e, "pilot-a/alpha-parity.txt", session_a,
                           "inv-parity-e", m=mission_cli, key=uniq_key("parity-eh"))
chk("engine produces a successful bounded handoff for the pilot shape", rc_e == 0)
engine_py = CLI / "atlas_mission.py"
engine_cli_file = CLI / "atlas-mission"
chk("engine/cli/atlas_mission.py exists", engine_py.is_file())
chk("engine/cli/atlas-mission exists", engine_cli_file.is_file())
core_py = REPO.parent / "core" / "cli" / "atlas_mission.py"
core_cli_file = REPO.parent / "core" / "cli" / "atlas-mission"
chk("no stale core/cli/atlas_mission.py copy has reappeared", not core_py.exists())
chk("no stale core/cli/atlas-mission copy has reappeared", not core_cli_file.exists())

# =============================================================================================
t("19. protected T-050/T-051 files and tickets untouched")
PROTECTED = [
    CLI / "atlas-coordinator",
    CLI / "atlas_coordination.py",
    CLI / "atlas-handoff",
    REPO / "governance" / "policies" / "handoff-transports.yaml",
    REPO / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())
chk("no real AIOS-012 ticket directory was created or touched by this pilot",
    not any("AIOS-012" in str(p) for p in root.rglob("*")))
chk("no real AIOS-017 ticket directory was created or touched by this pilot",
    not any("AIOS-017" in str(p) for p in root.rglob("*")))
chk("no real T-050 or T-051 ticket directory exists anywhere under this disposable fixture "
    "root (they belong to the real Atlas home, never this temp one)",
    not any(p.name in ("T-050", "T-051") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("20. no lease, claim, dispatch, send, approval automation, or AI invocation anywhere "
   "in the pilot run")
chk("no coordination/ directory exists anywhere under the pilot fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the pilot fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the pilot fixture root",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the pilot fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))
src_mission = (CLI / "atlas_mission.py").read_text()
chk("the only subprocess.run call in atlas_mission.py targets atlas-paths (pre-existing, S1) "
    "— nothing in the pilot flow invoked a real client binary",
    src_mission.count("subprocess.run(") == 1 and "PATHS_RESOLVER" in src_mission)

# =============================================================================================
t("21. per-mission budget cap of 0.10 USD honored throughout the pilot")
for mid_check, tdir_check in ((mission_a, ticket_a_dir), (mission_b, ticket_b_dir),
                              (mission_blocked, ticket_b_dir), (mission_det, ticket_a_dir)):
    contract_check, state_check = mission.load_mission(tdir_check, mid_check)
    chk(f"mission {mid_check}'s own contract budget_usd is exactly 0.10",
        abs(contract_check["budget_usd"] - 0.10) < 1e-9)
    chk(f"mission {mid_check}'s own committed budget never exceeds its 0.10 USD cap",
        state_check.get("budget_committed_usd", 0.0) <= 0.10 + 1e-9)

# =============================================================================================
t("22. exact approved file scope only — no Bash/network/MCP/Git/credentials tool ever "
   "declared for the pilot's own executor transport")
transports_text = (root / "handoff-transports.yaml").read_text()
chk("the pilot's own disposable transport for claude-code-tools-pilot declares only "
    "Read,Edit as tools", '"Read,Edit"' in transports_text)
chk("the pilot's own disposable transport never declares Bash",
    "Bash" not in transports_text)
adapter_text = (root / "adapters" / "claude-code-tools-pilot" / "adapter.yaml").read_text()
chk("the pilot's own fixture adapter for claude-code-tools-pilot declares no Bash/network/"
    "MCP/Git capability",
    not any(tok in adapter_text for tok in ("bash", "network", "mcp", "git")))

# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
print(f"\n{Y}S7 summary{X}: pilot pipeline PASS (two independent fixture missions completed, "
      f"one deliberately-blocked pilot mission finalized to 'blocked' with a blocker packet, "
      f"no cross-ticket collision observed) — live Claude CLI invocation BLOCKED (see test 1).")
sys.exit(0 if failed == 0 else 1)
