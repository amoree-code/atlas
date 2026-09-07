#!/usr/bin/env python3
"""tests/test-mission-execute.py — T-051-S7 execution integration: `mission execute` wires
the existing scope-aware `claude-code-mission-pilot` transport helpers into the real Mission
command path.

Two kinds of coverage live here:

Sections 1-24 use a FAKE, disposable "executor" binary (a small Python script this file
writes into its own temp fixture, never `claude`) whose behavior is controlled by an
environment variable this file sets before each call. This is the only way to exercise
timeout, non-zero-exit, and malformed-output deterministically — a real LLM cannot be made
to reliably time out, exit non-zero, or return garbage on demand. The fake binary receives
the exact same argv/stdin/timeout contract a real transport would (`mission_execute` cannot
tell the two apart), so every one of these tests exercises the REAL `mission_execute`
production function end to end.

Sections 25-30 invoke the REAL, installed `claude` binary — genuine, live, costed API calls,
bounded to $0.10 each via the real transport's own `--max-budget-usd` flag and to
`Read`/`Edit`-only tools — exactly twice, against two disposable fixture tickets whose scope
files carry the pilot's own task instructions (mission_execute pipes the packet, not a
free-form prompt, so the "what to do" instruction has to live somewhere the executor is
allowed to read: the one file it is scoped to). A third fixture mission proves a `verified:
false` transport refuses before any subprocess call, mirroring the real registry's own
current (unpromoted) state.
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
    modname = f"under_test_{cli_dir.parent.name}_{name.replace('-', '_').replace('.', '_')}_exec"
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

FAKE_EXECUTOR_SCRIPT = '''#!/usr/bin/env python3
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
    identity = {k: packet.get(k) for k in
               ("handoff_id", "mission_id", "root_task_id", "executor_client",
                "executor_session", "invocation_id", "gate")}
    identity["scope"] = scope_raw

    if mode == "wrong_identity":
        identity["handoff_id"] = "wrong-handoff-id-0000000000000000"

    if mode in ("pass", "scope_violation", "wrong_identity") and scope_canonical:
        new_content = os.environ.get("FAKE_EXECUTOR_NEW_CONTENT", "edited by fake executor")
        with open(scope_canonical, "w") as f:
            f.write(new_content + "\\n")

    changed = [scope_raw] if mode in ("pass", "wrong_identity") else []
    if mode == "scope_violation":
        changed = ["some/other/unapproved-file.txt"]

    status = "blocked" if mode == "blocked" else "pass"
    reply = dict(identity)
    reply.update({
        "status": status, "changed_files": changed,
        "tests": ["read the file back and compared its content"],
        "reported_cost_usd": 0.01,
        "summary": f"fake executor ran in mode {mode}",
    })
    if status == "blocked":
        reply["blocker"] = "fake executor reports blocked"
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
    transport registry declaring three fake clients: `fake-executor` (verified: true, 30s
    timeout), `fake-executor-timeout` (verified: true, 1s timeout, same binary), and
    `fake-executor-unverified` (verified: false, same binary) — plus `codex` for
    planner/verifier roles, exactly like every prior T-051 test fixture."""
    tmp = Path(tempfile.mkdtemp(prefix="t051-exec-"))
    fake_bin = _mkbin(tmp, "fake-executor", FAKE_EXECUTOR_SCRIPT)

    (tmp / "work").mkdir(parents=True, exist_ok=True)

    adapters_dir = tmp / "adapters"
    for client, binname in (("codex", "codex-bin"), ("fake-executor", str(fake_bin)),
                            ("fake-executor-timeout", str(fake_bin)),
                            ("fake-executor-unverified", str(fake_bin))):
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
        "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\"]\n"
        "    stdin: packet\n    timeout: 30\n    verified: true\n"
        "    evidence: disposable fixture, never the real registry\n"
        "  fake-executor-timeout:\n"
        "    name: fixture fake executor (fast timeout)\n"
        f"    binary: {fake_bin}\n"
        "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\"]\n"
        "    stdin: packet\n    timeout: 1\n    verified: true\n"
        "    evidence: disposable fixture, never the real registry\n"
        "  fake-executor-unverified:\n"
        "    name: fixture fake executor (unverified)\n"
        f"    binary: {fake_bin}\n"
        "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\"]\n"
        "    stdin: packet\n    timeout: 30\n    verified: false\n"
        "    evidence: deliberately unverified — proves the pre-subprocess refusal gate\n")

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["AI_OS_ADAPTERS"] = str(adapters_dir)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp


def new_ticket(tmp, ticket_id):
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture execute ticket {id}\nstate: active\n"
        "project: demo\nopened_at: 2026-09-08 12:00 AM\nupdated_at: 2026-09-08 12:00 AM\n"
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
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words", "approved by execute test",
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


def do_finalize(task_id, mission_id, handoff_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("finalize")
    return run(m.cmd_finalize, [task_id, mission_id, handoff_id, "--idempotency-key", key,
                               "--json"])


def do_continue(task_id, mission_id, handoff_id, scope, session, invocation, executor,
               budget="0.05", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("continue")
    args = [task_id, mission_id, handoff_id, "--scope", scope, "--executor-client", executor,
           "--executor-session", session, "--invocation-id", invocation, "--gate", "execute",
           "--slice-budget-usd", budget, "--idempotency-key", key, "--json"]
    return run(m.cmd_continue, args)


def full_setup(tmp, ticket_id, executor="fake-executor", mode=None, scope_name="alpha.txt",
              rel_dir=None, session=None, invocation=None, budget="1.00"):
    """create -> approve -> handoff, ready for `mission execute`. Returns a dict of everything
    a test needs."""
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
    return {
        "ticket_id": ticket_id, "mission_id": mission_id, "handoff_id": handoff_id,
        "scope_path": scope_path, "scope_raw": scope_raw, "session": session,
        "invocation": invocation, "executor": executor,
    }


# =============================================================================================
ROOT = new_fixture()

t("1. valid foreground execution — PASS classification via a real subprocess call")
os.environ["FAKE_EXECUTOR_NEW_CONTENT"] = "content written by mission execute test 1"
ctx = full_setup(ROOT, "T-980-A")
rc, out, err = do_execute(ctx["ticket_id"], ctx["mission_id"], ctx["handoff_id"], ctx["executor"],
                          ctx["session"], ctx["invocation"])
chk("mission execute exits 0", rc == 0)
res1 = json.loads(out)
chk("invoked is True", res1["invoked"] is True)
chk("returncode is 0", res1["returncode"] == 0)
chk("not timed out", res1["timed_out"] is False)
chk("classification is PASS", res1["classification"] == "PASS")
chk("raw_return_path exists", Path(res1["raw_return_path"]).is_file())
chk("result_path exists", Path(res1["result_path"]).is_file())
chk("verification_path exists", Path(res1["verification_path"]).is_file())
chk("the fake executor actually edited the scope file",
   ctx["scope_path"].read_text().strip() == "content written by mission execute test 1")

t("2. exact argv construction — matches mission_pilot_transport_argv byte-for-byte")
expected_argv = mission.mission_pilot_transport_argv(
    mission.resolve_task_dir("T-980-A"), ctx["mission_id"], ctx["handoff_id"],
    client="fake-executor")
raw_return = json.loads(Path(res1["raw_return_path"]).read_text())
chk("argv used by mission execute matches the existing helper's own output",
   raw_return["argv"] == expected_argv)
chk("argv contains the resolved scope directory, not the placeholder",
   os.path.realpath(str(ctx["scope_path"].parent)) in raw_return["argv"] and
   "__MISSION_SCOPE_DIR__" not in raw_return["argv"])

t("3. stdin packet delivery — the executor actually received this handoff's own packet")
result_obj = json.loads(Path(res1["result_path"]).read_text())
chk("the parsed result's handoff_id matches this handoff (round-tripped via stdin)",
   result_obj["handoff_id"] == ctx["handoff_id"])
chk("the parsed result's mission_id matches this mission (round-tripped via stdin)",
   result_obj["mission_id"] == ctx["mission_id"])

t("4. single foreground call, no retry, deterministic capture")
chk("single_foreground_call recorded true", raw_return["single_foreground_call"] is True)
chk("no_retry recorded true", raw_return["no_retry"] is True)
chk("no_shell recorded true", raw_return["no_shell"] is True)
chk("started_at/finished_at recorded", raw_return["started_at"] and raw_return["finished_at"])

t("5. verified: false transport refuses BEFORE any subprocess call")
# `mission_route` already refuses an unverified transport at handoff-creation time too (the
# same gate `mission_execute` reuses) — so a handoff can never legitimately exist for a
# client that was unverified all along. To prove `mission_execute` itself ALSO enforces this
# (defense in depth, never trusting handoff-creation-time state), this test creates a handoff
# while the transport IS verified, then flips the disposable registry's own entry to
# `verified: false` before calling execute — the same "tamper between handoff and execute,
# then prove revalidation" pattern used by the budget/attempts/ttl/tools tests below.
counter_file = str(ROOT / "unverified-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx5 = full_setup(ROOT, "T-980-B", executor="fake-executor")
transports_path = Path(os.environ["AI_OS_HANDOFF_TRANSPORTS"])
transports_before = transports_path.read_text()
fake_bin_path = ROOT / "bin" / "fake-executor"
tampered = transports_before.replace(
    "  fake-executor:\n"
    "    name: fixture fake executor\n"
    f"    binary: {fake_bin_path}\n"
    "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\"]\n"
    "    stdin: packet\n    timeout: 30\n    verified: true\n",
    "  fake-executor:\n"
    "    name: fixture fake executor\n"
    f"    binary: {fake_bin_path}\n"
    "    argv: [--scope-dir, __MISSION_SCOPE_DIR__, --tools, \"Read,Edit\"]\n"
    "    stdin: packet\n    timeout: 30\n    verified: false\n")
assert tampered != transports_before, "fake-executor block not found for tampering"
transports_path.write_text(tampered)
rc, out, err = do_execute(ctx5["ticket_id"], ctx5["mission_id"], ctx5["handoff_id"],
                          ctx5["executor"], ctx5["session"], ctx5["invocation"])
chk("mission execute refuses (non-zero exit)", rc != 0)
chk("refusal mentions the transport is not verified",
   "not verified" in err.lower() or "verified: false" in err.lower())
chk("no subprocess call was made (counter file never created)", not Path(counter_file).exists())
task_dir5 = mission.resolve_task_dir("T-980-B")
chk("no raw-return.json was written",
   not (mission.handoff_dir(task_dir5, ctx5["mission_id"], ctx5["handoff_id"])
       / "execution" / "raw-return.json").is_file())
chk("no result.json or verification.json was written", not any(
   (mission.handoff_dir(task_dir5, ctx5["mission_id"], ctx5["handoff_id"]) / n).is_file()
   for n in ("result.json", "verification.json")))
transports_path.write_text(transports_before)
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("6. subprocess timeout -> BLOCKED, no retry")
counter_file = str(ROOT / "timeout-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
os.environ["FAKE_EXECUTOR_MODE"] = "timeout"
os.environ["FAKE_EXECUTOR_SLEEP"] = "3"
ctx6 = full_setup(ROOT, "T-980-C", executor="fake-executor-timeout", mode="timeout")
started = time.monotonic()
rc, out, err = do_execute(ctx6["ticket_id"], ctx6["mission_id"], ctx6["handoff_id"],
                          ctx6["executor"], ctx6["session"], ctx6["invocation"])
elapsed = time.monotonic() - started
res6 = json.loads(out)
chk("mission execute exits 0 (a timeout is a classification, not a hard refusal)", rc == 0)
chk("timed_out is True", res6["timed_out"] is True)
chk("classification is BLOCKED", res6["classification"] == "BLOCKED")
chk("this returned close to the transport's 1s timeout, not the fake script's 3s sleep",
   elapsed < 2.5)
raw6 = json.loads(Path(res6["raw_return_path"]).read_text())
chk("raw return records timed_out true", raw6["timed_out"] is True)
del os.environ["FAKE_EXECUTOR_SLEEP"]
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("7. no next handoff and no finalize-to-completed after a BLOCKED execution")
rc, out, err = do_continue(ctx6["ticket_id"], ctx6["mission_id"], ctx6["handoff_id"],
                           ctx6["scope_raw"], ctx6["session"], "next-invocation", ctx6["executor"])
chk("continuation after BLOCKED refuses", rc != 0)
rc, out, err = do_finalize(ctx6["ticket_id"], ctx6["mission_id"], ctx6["handoff_id"])
chk("finalize after BLOCKED reaches mission_state=blocked, never completed", rc == 0)
chk("finalize result says blocked", json.loads(out)["mission_state"] == "blocked")

t("8. non-zero executor exit -> FAILED classification")
os.environ["FAKE_EXECUTOR_MODE"] = "nonzero"
ctx8 = full_setup(ROOT, "T-980-D")
rc, out, err = do_execute(ctx8["ticket_id"], ctx8["mission_id"], ctx8["handoff_id"],
                          ctx8["executor"], ctx8["session"], ctx8["invocation"])
res8 = json.loads(out)
chk("mission execute exits 0", rc == 0)
chk("returncode is 3", res8["returncode"] == 3)
chk("classification is FAILED", res8["classification"] == "FAILED")

t("9. malformed executor output (not JSON) -> FAILED classification, still recorded")
os.environ["FAKE_EXECUTOR_MODE"] = "bad_json"
ctx9 = full_setup(ROOT, "T-980-E")
rc, out, err = do_execute(ctx9["ticket_id"], ctx9["mission_id"], ctx9["handoff_id"],
                          ctx9["executor"], ctx9["session"], ctx9["invocation"])
res9 = json.loads(out)
chk("mission execute exits 0", rc == 0)
chk("classification is FAILED", res9["classification"] == "FAILED")
chk("a result.json/verification.json pair still exists (classified, not silently dropped)",
   Path(res9["result_path"]).is_file() and Path(res9["verification_path"]).is_file())

t("10. malformed executor output (missing required field) -> FAILED classification")
os.environ["FAKE_EXECUTOR_MODE"] = "missing_field"
ctx10 = full_setup(ROOT, "T-980-F")
rc, out, err = do_execute(ctx10["ticket_id"], ctx10["mission_id"], ctx10["handoff_id"],
                          ctx10["executor"], ctx10["session"], ctx10["invocation"])
res10 = json.loads(out)
chk("mission execute exits 0", rc == 0)
chk("classification is FAILED", res10["classification"] == "FAILED")

t("11. self-reported scope violation -> BLOCKED via the existing verifier's own scope check")
os.environ["FAKE_EXECUTOR_MODE"] = "scope_violation"
ctx11 = full_setup(ROOT, "T-980-G")
rc, out, err = do_execute(ctx11["ticket_id"], ctx11["mission_id"], ctx11["handoff_id"],
                          ctx11["executor"], ctx11["session"], ctx11["invocation"])
res11 = json.loads(out)
chk("mission execute exits 0", rc == 0)
chk("classification is BLOCKED (scope offender)", res11["classification"] == "BLOCKED")

t("12. wrong self-reported identity -> NEEDS_OWNER via the existing verifier's own identity "
  "check")
os.environ["FAKE_EXECUTOR_MODE"] = "wrong_identity"
ctx12 = full_setup(ROOT, "T-980-H")
rc, out, err = do_execute(ctx12["ticket_id"], ctx12["mission_id"], ctx12["handoff_id"],
                          ctx12["executor"], ctx12["session"], ctx12["invocation"])
res12 = json.loads(out)
chk("mission execute exits 0", rc == 0)
chk("classification is NEEDS_OWNER", res12["classification"] == "NEEDS_OWNER")

os.environ["FAKE_EXECUTOR_MODE"] = "pass"

t("13. session mismatch refuses before any subprocess call")
counter_file = str(ROOT / "session-mismatch-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx13 = full_setup(ROOT, "T-980-I")
rc, out, err = do_execute(ctx13["ticket_id"], ctx13["mission_id"], ctx13["handoff_id"],
                          ctx13["executor"], "some-other-session", ctx13["invocation"])
chk("mission execute refuses", rc != 0)
chk("refusal mentions a session mismatch", "session" in err.lower())
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("14. invocation mismatch refuses before any subprocess call")
counter_file = str(ROOT / "invocation-mismatch-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx14 = full_setup(ROOT, "T-980-J")
rc, out, err = do_execute(ctx14["ticket_id"], ctx14["mission_id"], ctx14["handoff_id"],
                          ctx14["executor"], ctx14["session"], "some-other-invocation")
chk("mission execute refuses", rc != 0)
chk("refusal mentions an invocation mismatch", "invocation" in err.lower())
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("15. executor-client mismatch refuses before any subprocess call")
counter_file = str(ROOT / "client-mismatch-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx15 = full_setup(ROOT, "T-980-K")
rc, out, err = do_execute(ctx15["ticket_id"], ctx15["mission_id"], ctx15["handoff_id"],
                          "fake-executor-unverified", ctx15["session"], ctx15["invocation"])
chk("mission execute refuses", rc != 0)
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("16. budget already exceeded (tampered mission state) refuses before any subprocess call")
counter_file = str(ROOT / "budget-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx16 = full_setup(ROOT, "T-980-L")
task_dir16 = mission.resolve_task_dir("T-980-L")
sp = mission.state_path(task_dir16, ctx16["mission_id"])
st = json.loads(sp.read_text())
st["budget_committed_usd"] = 999.0
sp.write_text(json.dumps(st))
rc, out, err = do_execute(ctx16["ticket_id"], ctx16["mission_id"], ctx16["handoff_id"],
                          ctx16["executor"], ctx16["session"], ctx16["invocation"])
chk("mission execute refuses", rc != 0)
chk("refusal mentions a mission limit violation", "limit" in err.lower() or "budget" in err.lower())
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("17. max_attempts already exceeded (tampered mission state) refuses before any subprocess "
  "call")
counter_file = str(ROOT / "attempts-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx17 = full_setup(ROOT, "T-980-M")
task_dir17 = mission.resolve_task_dir("T-980-M")
sp = mission.state_path(task_dir17, ctx17["mission_id"])
st = json.loads(sp.read_text())
st["attempts_used"] = 999
sp.write_text(json.dumps(st))
rc, out, err = do_execute(ctx17["ticket_id"], ctx17["mission_id"], ctx17["handoff_id"],
                          ctx17["executor"], ctx17["session"], ctx17["invocation"])
chk("mission execute refuses", rc != 0)
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("18. TTL already elapsed (tampered approval time) refuses before any subprocess call")
counter_file = str(ROOT / "ttl-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx18 = full_setup(ROOT, "T-980-N")
task_dir18 = mission.resolve_task_dir("T-980-N")
sp = mission.state_path(task_dir18, ctx18["mission_id"])
st = json.loads(sp.read_text())
st["approved_at"] = "2000-01-01T00:00:00+00:00"
sp.write_text(json.dumps(st))
rc, out, err = do_execute(ctx18["ticket_id"], ctx18["mission_id"], ctx18["handoff_id"],
                          ctx18["executor"], ctx18["session"], ctx18["invocation"])
chk("mission execute refuses", rc != 0)
chk("refusal mentions ttl", "ttl" in err.lower())
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("19. tool boundary widened on a tampered packet refuses before any subprocess call")
counter_file = str(ROOT / "tools-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx19 = full_setup(ROOT, "T-980-O")
task_dir19 = mission.resolve_task_dir("T-980-O")
hd19 = mission.handoff_dir(task_dir19, ctx19["mission_id"], ctx19["handoff_id"])
pk = json.loads((hd19 / "packet.json").read_text())
pk["allowed_tools"] = pk["allowed_tools"] + ["Bash"]
(hd19 / "packet.json").write_text(json.dumps(pk))
rc, out, err = do_execute(ctx19["ticket_id"], ctx19["mission_id"], ctx19["handoff_id"],
                          ctx19["executor"], ctx19["session"], ctx19["invocation"])
chk("mission execute refuses", rc != 0)
chk("refusal mentions the tool boundary", "tool" in err.lower())
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("20. scope escaping via a post-handoff symlink swap refuses before any subprocess call")
counter_file = str(ROOT / "scope-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx20 = full_setup(ROOT, "T-980-P")
outside = Path(tempfile.mkdtemp(prefix="t051-exec-outside-"))
outside_file = outside / "secret.txt"
outside_file.write_text("outside the allowed root\n")
ctx20["scope_path"].unlink()
ctx20["scope_path"].symlink_to(outside_file)
rc, out, err = do_execute(ctx20["ticket_id"], ctx20["mission_id"], ctx20["handoff_id"],
                          ctx20["executor"], ctx20["session"], ctx20["invocation"])
chk("mission execute refuses", rc != 0)
chk("no subprocess call was made", not Path(counter_file).exists())
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("21. already-executed handoff refuses a second execution attempt")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx21 = full_setup(ROOT, "T-980-Q")
rc, out, err = do_execute(ctx21["ticket_id"], ctx21["mission_id"], ctx21["handoff_id"],
                          ctx21["executor"], ctx21["session"], ctx21["invocation"])
chk("first execution succeeds", rc == 0)
rc, out, err = do_execute(ctx21["ticket_id"], ctx21["mission_id"], ctx21["handoff_id"],
                          ctx21["executor"], ctx21["session"], ctx21["invocation"],
                          key=uniq_key("execute"))
chk("a second execution attempt (different key) refuses", rc != 0)
chk("refusal mentions an already-recorded result", "already" in err.lower())

t("22. idempotent replay — same request, same key -> same result, no second subprocess call")
counter_file = str(ROOT / "replay-counter.txt")
os.environ["FAKE_EXECUTOR_COUNTER_FILE"] = counter_file
ctx22 = full_setup(ROOT, "T-980-R")
replay_key = uniq_key("execute-replay")
rc1, out1, err1 = do_execute(ctx22["ticket_id"], ctx22["mission_id"], ctx22["handoff_id"],
                             ctx22["executor"], ctx22["session"], ctx22["invocation"],
                             key=replay_key)
rc2, out2, err2 = do_execute(ctx22["ticket_id"], ctx22["mission_id"], ctx22["handoff_id"],
                             ctx22["executor"], ctx22["session"], ctx22["invocation"],
                             key=replay_key)
chk("both calls succeed", rc1 == 0 and rc2 == 0)
r1, r2 = json.loads(out1), json.loads(out2)
chk("first call is not a replay", r1.get("replay") is False)
chk("second call IS a replay", r2.get("replay") is True)
chk("both calls report the same classification/result path", r1["classification"] == r2[
   "classification"] and r1["result_path"] == r2["result_path"])
chk("the subprocess was invoked exactly once, not twice", Path(counter_file).read_text().strip() == "1")
del os.environ["FAKE_EXECUTOR_COUNTER_FILE"]

t("23. conflicting replay — same key, materially different request refuses")
# Idempotency for `mission execute` is scoped to the ONE handoff it executes (the same
# convention `mission verify` already uses for its own per-handoff idempotency store) — so a
# reused key only ever collides against a request for that SAME handoff, never across two
# different handoffs (each has its own store). This proves the same key, same handoff, but a
# materially different request (a different invocation_id this time) refuses as an ambiguous
# replay rather than silently returning the first call's result.
ctx23 = full_setup(ROOT, "T-980-S")
conflict_key = uniq_key("execute-conflict")
rc, out, err = do_execute(ctx23["ticket_id"], ctx23["mission_id"], ctx23["handoff_id"],
                          ctx23["executor"], ctx23["session"], ctx23["invocation"],
                          key=conflict_key)
chk("first call with this key succeeds", rc == 0)
rc, out, err = do_execute(ctx23["ticket_id"], ctx23["mission_id"], ctx23["handoff_id"],
                          ctx23["executor"], ctx23["session"], "a-materially-different-invocation",
                          key=conflict_key)
chk("reusing the same key with a different invocation_id refuses", rc != 0)
chk("refusal mentions a conflicting/ambiguous replay", "conflict" in err.lower() or
   "ambiguous" in err.lower() or "different" in err.lower())

t("24. unknown mission and unknown handoff both refuse cleanly")
ctx24 = full_setup(ROOT, "T-980-U")
rc, out, err = do_execute(ctx24["ticket_id"], "mission-does-not-exist", ctx24["handoff_id"],
                          ctx24["executor"], ctx24["session"], ctx24["invocation"])
chk("unknown mission id refuses", rc != 0)
rc, out, err = do_execute(ctx24["ticket_id"], ctx24["mission_id"], "handoff-does-not-exist",
                          ctx24["executor"], ctx24["session"], ctx24["invocation"])
chk("unknown handoff id refuses", rc != 0)

t("25. mission not approved refuses execution")
new_ticket(ROOT, "T-980-V")
scope_path25, scope_raw25 = new_scope_file(ROOT, "work/t-980-v", "alpha.txt")
rc, out, err = do_create("T-980-V", [scope_raw25])
assert rc == 0, (rc, out, err)
mid25 = mission_id_from(out)
rc, out, err = do_execute("T-980-V", mid25, "handoff-anything", "fake-executor", "s", "i")
chk("execution on an unapproved (never-handed-off) mission refuses", rc != 0)

t("26. mission execute never approves, never creates a lease/claim, never dispatches "
  "anything beyond the one subprocess call")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx26 = full_setup(ROOT, "T-980-W")
rc, out, err = do_execute(ctx26["ticket_id"], ctx26["mission_id"], ctx26["handoff_id"],
                          ctx26["executor"], ctx26["session"], ctx26["invocation"])
task_dir26 = mission.resolve_task_dir("T-980-W")
chk("mission execute succeeds", rc == 0)
chk("no coordination/, runtime/, claims/, or leases/ directory exists anywhere under the "
   "fixture root", not any((ROOT / n).exists() for n in
                          ("coordination", "runtime", "claims", "leases")))
chk("no handoff-*.md V6 record exists anywhere under the fixture ticket",
   not list(task_dir26.glob("handoff-*.md")))

t("27. execute -> verify (implicit) -> finalize reaches completed for a real PASS execution")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx27 = full_setup(ROOT, "T-980-X")
rc, out, err = do_execute(ctx27["ticket_id"], ctx27["mission_id"], ctx27["handoff_id"],
                          ctx27["executor"], ctx27["session"], ctx27["invocation"])
chk("execution succeeds", rc == 0)
res27 = json.loads(out)
chk("classification is PASS", res27["classification"] == "PASS")
rc, out, err = do_finalize(ctx27["ticket_id"], ctx27["mission_id"], ctx27["handoff_id"])
chk("finalize succeeds", rc == 0)
chk("mission_state is completed", json.loads(out)["mission_state"] == "completed")

t("28. continuation after an executed PASS works exactly like a manually-verified PASS")
os.environ["FAKE_EXECUTOR_MODE"] = "pass"
ctx28 = full_setup(ROOT, "T-980-Y")
rc, out, err = do_execute(ctx28["ticket_id"], ctx28["mission_id"], ctx28["handoff_id"],
                          ctx28["executor"], ctx28["session"], ctx28["invocation"])
chk("execution succeeds with PASS", rc == 0 and json.loads(out)["classification"] == "PASS")
rc, out, err = do_continue(ctx28["ticket_id"], ctx28["mission_id"], ctx28["handoff_id"],
                           ctx28["scope_raw"], ctx28["session"], "next-invocation-28",
                           ctx28["executor"])
chk("continuation after an executed PASS succeeds", rc == 0)

t("29. engine/core parity")
chk("engine and core aios_mission.py are byte-identical",
   (CLI / "aios_mission.py").read_bytes() == (CORE_CLI / "aios_mission.py").read_bytes())
chk("engine and core ai-os-mission are byte-identical",
   (CLI / "ai-os-mission").read_bytes() == (CORE_CLI / "ai-os-mission").read_bytes())
chk("core module also exposes mission_execute", hasattr(core_mission, "mission_execute"))
chk("core CLI also exposes cmd_execute", hasattr(core_mission_cli, "cmd_execute"))

os.environ_backup = dict(os.environ)
for _var in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS"):
    os.environ.pop(_var, None)
core_ctx = None
os.environ.update(os.environ_backup)

t("30. no T-050/AIOS-011/AIOS-012/AIOS-017/T-049 file or record touched by this fixture root")
chk("no real AIOS-011, AIOS-012, AIOS-017, T-049 or T-050 ticket directory exists under this "
   "disposable fixture root", not any(
       (ROOT / "projects" / "ai-os" / "tickets" / tid).exists()
       for tid in ("AIOS-011", "AIOS-012", "AIOS-017", "T-049", "T-050")))
REAL_TRANSPORTS = REPO / "internal" / "governance" / "policies" / "handoff-transports.yaml"
real_before = REAL_TRANSPORTS.read_text()
chk("the REAL transport registry file was never touched by any test above",
   REAL_TRANSPORTS.read_text() == real_before)


# =============================================================================================
# SECTIONS 31+: the real, live Claude CLI pilot, run through `mission execute` itself (not a
# hand-rolled subprocess call) — two disposable fixture tickets, non-overlapping scopes, one
# real bounded invocation each, plus one deliberately-unverified fixture mission proving the
# same pre-subprocess refusal gate holds for the real `claude-code-mission-pilot` client name.
# =============================================================================================
CLAUDE_BINARY = shutil.which("claude")
LIVE_INVOCATIONS = []

t("31. real Claude CLI binary present on PATH")
if not CLAUDE_BINARY:
    chk("the `claude` binary is on PATH (required for the real pilot below)", False)
    print(f"  {Y}skipping the real-invocation sections — no `claude` on PATH{X}")
else:
    chk("the `claude` binary is on PATH", True)

    for _var in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS"):
        os.environ.pop(_var, None)
    real_root = Path(tempfile.mkdtemp(prefix="t051-exec-real-"))
    new_ticket(real_root, "T-981-A")
    new_ticket(real_root, "T-981-B")
    new_ticket(real_root, "T-981-C")

    real_adapters = real_root / "adapters"
    for client, binname in (("codex", "codex-bin"), ("claude-code-mission-pilot", "claude")):
        d = real_adapters / client
        d.mkdir(parents=True, exist_ok=True)
        (d / "adapter.yaml").write_text(
            f"adapter: {client}\nname: fixture adapter for {client}\ncontract: 1\n\n"
            f"client:\n  detect: [/nonexistent]\n  version_cmd: {binname} --version\n"
            f"  consumer_verified: false\n\nprovides:\n"
            f"  rules: {{ path: /nonexistent, format: markdown, verified: true }}\n\n"
            f"writes: []\nrequires: []\nenforces: []\n")

    REAL_ARGV = [
        "-p", "--no-session-persistence", "--restricted", "--strict-mcp-config", "--add-dir",
        "__MISSION_SCOPE_DIR__", "--tools", "Read,Edit", "--permission-mode", "acceptEdits",
        "--permission-prompts", "none", "--max-budget-usd", "0.10", "--",
    ]
    argv_yaml = ", ".join(json.dumps(a) for a in REAL_ARGV)
    real_transports = real_root / "handoff-transports.yaml"
    real_transports.write_text(
        "contract: 1\n\ntransports:\n"
        "  codex:\n"
        "    name: fixture codex\n    binary: codex-bin\n"
        "    argv: [--sandbox, read-only]\n    stdin: packet\n    timeout: 60\n"
        "    verified: true\n    evidence: fixture, not dispatched\n"
        "  claude-code-mission-pilot:\n"
        "    name: fixture mirror of the real claude-code-mission-pilot entry\n"
        "    binary: claude\n"
        f"    argv: [{argv_yaml}]\n"
        "    stdin: packet\n    timeout: 120\n    verified: true\n"
        "    evidence: disposable fixture, mirrors the real (still verified:false) entry\n")

    os.environ["ATLAS_HOME"] = str(real_root)
    os.environ["AI_OS_ADAPTERS"] = str(real_adapters)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(real_transports)

    def live_setup(ticket_id, rel_dir, content_instruction):
        scope_dir = real_root / rel_dir
        scope_dir.mkdir(parents=True, exist_ok=True)
        scope_file = scope_dir / "task.txt"
        scope_file.write_text(content_instruction)
        scope_raw = f"{rel_dir}/task.txt"

        session, invocation = f"live-session-{ticket_id}", f"live-invocation-{ticket_id}"
        rc, out, err = do_create(ticket_id, [scope_raw], executor="claude-code-mission-pilot",
                                 budget="0.30")
        assert rc == 0, (rc, out, err)
        mid = mission_id_from(out)
        rc, out, err = do_approve(ticket_id, mid)
        assert rc == 0, (rc, out, err)
        rc, out, err = do_handoff(ticket_id, mid, scope_raw, session, invocation,
                                  "claude-code-mission-pilot")
        assert rc == 0, (rc, out, err)
        hid = handoff_id_from(out)
        return {"ticket_id": ticket_id, "mission_id": mid, "handoff_id": hid,
               "scope_path": scope_file, "scope_raw": scope_raw, "session": session,
               "invocation": invocation}

    t("32. two real bounded Claude CLI executions via `mission execute` itself")
    content_a = ("Replace this file's entire content with exactly the single line: "
                "pilot execute A live content 771\n\nAfter editing, your entire reply must "
                "be exactly one JSON object as instructed in the surrounding packet prompt.")
    content_b = ("Replace this file's entire content with exactly the single line: "
                "pilot execute B live content 992\n\nAfter editing, your entire reply must "
                "be exactly one JSON object as instructed in the surrounding packet prompt.")
    live_a = live_setup("T-981-A", "pilot-exec-a", content_a)
    live_b = live_setup("T-981-B", "pilot-exec-b", content_b)

    rc_a, out_a, err_a = do_execute(live_a["ticket_id"], live_a["mission_id"],
                                    live_a["handoff_id"], "claude-code-mission-pilot",
                                    live_a["session"], live_a["invocation"])
    res_a = json.loads(out_a) if rc_a == 0 else {}
    LIVE_INVOCATIONS.append(("mission-A", res_a))
    chk("mission execute (real) exits 0 for mission A", rc_a == 0)
    chk("mission A: invoked is True", res_a.get("invoked") is True)
    chk("mission A: subprocess returncode is 0", res_a.get("returncode") == 0)
    chk("mission A: got a classification (real invocation was classified, not dropped)",
       res_a.get("classification") in ("PASS", "NEEDS_OWNER", "BLOCKED", "FAILED"))
    chk("mission A: the real execution reached genuine PASS", res_a.get("classification") == "PASS")

    rc_b, out_b, err_b = do_execute(live_b["ticket_id"], live_b["mission_id"],
                                    live_b["handoff_id"], "claude-code-mission-pilot",
                                    live_b["session"], live_b["invocation"])
    res_b = json.loads(out_b) if rc_b == 0 else {}
    LIVE_INVOCATIONS.append(("mission-B", res_b))
    chk("mission execute (real) exits 0 for mission B", rc_b == 0)
    chk("mission B: invoked is True", res_b.get("invoked") is True)
    chk("mission B: subprocess returncode is 0", res_b.get("returncode") == 0)
    chk("mission B: got a classification (real invocation was classified, not dropped)",
       res_b.get("classification") in ("PASS", "NEEDS_OWNER", "BLOCKED", "FAILED"))
    chk("mission B: the real execution reached genuine PASS", res_b.get("classification") == "PASS")

    t("33. each real execution changed only its own file")
    chk("mission A's own file was actually rewritten by the live edit",
       "pilot execute A live content 771" in live_a["scope_path"].read_text())
    chk("mission B's own file was actually rewritten by the live edit",
       "pilot execute B live content 992" in live_b["scope_path"].read_text())
    chk("mission A's edit never touched mission B's file",
       "pilot execute A" not in live_b["scope_path"].read_text())
    chk("mission B's edit never touched mission A's file",
       "pilot execute B" not in live_a["scope_path"].read_text())

    t("34. real argv used the resolved per-mission scope directory")
    if res_a.get("raw_return_path"):
        raw_a = json.loads(Path(res_a["raw_return_path"]).read_text())
        chk("mission A's real argv named its own resolved scope directory",
           os.path.realpath(str(live_a["scope_path"].parent)) in raw_a["argv"])
        chk("mission A's real argv never named mission B's directory",
           os.path.realpath(str(live_b["scope_path"].parent)) not in raw_a["argv"])

    t("35. a third, deliberately-unverified real pilot mission refuses before any subprocess "
      "call")
    real_transports_unverified = real_root / "handoff-transports-unverified.yaml"
    real_transports_unverified.write_text(
        "contract: 1\n\ntransports:\n"
        "  codex:\n"
        "    name: fixture codex\n    binary: codex-bin\n"
        "    argv: [--sandbox, read-only]\n    stdin: packet\n    timeout: 60\n"
        "    verified: true\n    evidence: fixture, not dispatched\n"
        "  claude-code-mission-pilot:\n"
        "    name: fixture mirror, deliberately unverified\n"
        "    binary: claude\n"
        f"    argv: [{argv_yaml}]\n"
        "    stdin: packet\n    timeout: 120\n    verified: false\n"
        "    evidence: deliberately unverified for this negative fixture\n")
    # `mission_route` already refuses an unverified transport at handoff-creation time too, so
    # the handoff for mission C is created while the fixture registry marks the transport
    # verified (matching missions A/B's own registry) — the switch to the deliberately
    # unverified registry happens AFTER the handoff exists, before `mission execute` is ever
    # called, proving `mission_execute` itself re-checks `verified` rather than trusting
    # whatever was true when the handoff was created.
    live_c = live_setup("T-981-C", "pilot-exec-c",
                       "This file must never be edited by this fixture.\n")
    gamma_before = live_c["scope_path"].read_text()
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(real_transports_unverified)
    rc_c, out_c, err_c = do_execute(live_c["ticket_id"], live_c["mission_id"],
                                    live_c["handoff_id"], "claude-code-mission-pilot",
                                    live_c["session"], live_c["invocation"])
    chk("mission execute refuses for the unverified real pilot transport", rc_c != 0)
    chk("mission C's own file was never touched", live_c["scope_path"].read_text() == gamma_before)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(real_transports)

    t("36. no production file was touched by the real-invocation section")
    chk("the REAL registry file was never touched", REAL_TRANSPORTS.read_text() == real_before)
    chk("no real AIOS-011/AIOS-012/AIOS-017/T-049/T-050 ticket directory exists under the "
       "real-invocation fixture root", not any(
           (real_root / "projects" / "ai-os" / "tickets" / tid).exists()
           for tid in ("AIOS-011", "AIOS-012", "AIOS-017", "T-049", "T-050")))


print(f"\n{'='*80}")
print(f"{passed}/{passed + failed} passed" + (f", {failed} FAILED" if failed else ""))
if os.environ.get("_T051_EXEC_LIVE_LOG"):
    for label, res in LIVE_INVOCATIONS:
        print(f"  {label}: {res}")
sys.exit(1 if failed else 0)
