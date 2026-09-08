#!/usr/bin/env python3
"""tests/test-coordinator-routing.py — T-050-S1: deterministic route, owner-gated dispatch.

`cli/atlas-coordinator` adds exactly two things on top of the existing AIOS-011 handoff
records and the AIOS-012 verified transport registry: `route` (resolve who a task's intent
belongs to, from a declared policy, and print the decision) and `dispatch` (verify an
existing, explicit owner approval matches a handoff record exactly, then call the existing
`atlas handoff send`). Neither is a scheduler, a lease, a lock, a queue or a daemon — most of
the scenarios below check an *absence*, not just a presence.

Every scenario runs against a disposable ATLAS_HOME fixture built by `make_ticket_home()`,
matching the shape `atlas-paths ticket <id>` actually resolves (`projects/<proj>/tickets/
<id>/task.md`) — the same fixture shape `test-agent-handoff-identity.py` already uses.
Nothing here touches the real workspace, the real routing policy's *effect*, or any real
ticket; the real `coordinator-routing.yaml` and `handoff-transports.yaml` are read read-only
by the "real policy resolves" scenarios, and never written by any scenario.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli"
ATLAS = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))

G, Y, R, D, X = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = Y = R = D = X = ""
passed = failed = 0


def runtime_entries(rt_dir):
    """Sorted relative paths under a runtime dir, or [] if it doesn't exist yet — used to
    compare a *snapshot* of runtime state before/after one operation, rather than assuming
    the directory is empty outright (T-050-S6-R1's dispatch scenario legitimately populates
    `runtime/coordination/` earlier in this same shared fixture root)."""
    return sorted(str(p.relative_to(rt_dir)) for p in rt_dir.rglob("*")) if rt_dir.exists() \
        else []


def chk(desc, ok):
    global passed, failed
    if ok:
        print(f"  {G}PASS{X} {desc}"); passed += 1
    else:
        print(f"  {R}FAIL{X} {desc}"); failed += 1


def t(label):
    print(f"\n{D}— {label}{X}")


def _load(name):
    spec = importlib.util.spec_from_loader(
        f"under_test_{name.replace('-', '_')}",
        importlib.machinery.SourceFileLoader(f"under_test_{name.replace('-', '_')}", str(CLI / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


handoff = _load("atlas-handoff")
coordinator = _load("atlas-coordinator")
coord = _load("atlas_coordination.py")

# T-050-S6-R1: `coordinator dispatch` now requires --lease-id/--client/--session and verifies
# them before it ever reaches the pre-existing approval-tuple checks these S1-S3 dispatch
# scenarios exercise. These dummy, validly-shaped (but not necessarily real) values let a
# dispatch call reach the approval logic under test; only the "fully approved, consistent"
# scenario below needs a genuinely active lease + claim, since it is the one scenario that
# passes every pre-existing check and reaches the new conflict-protection gate for real.
DISPATCH_LEASE_FLAGS = ["--lease-id", "lease-dummy0000000000000000000000",
                       "--client", "dummy-client", "--session", "dummy-session"]


def make_ticket_home(root, project="demo", ticket_id="T-900"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for coordinator tests\nstate: active\n"
        "project: {project}\nopened_at: 2026-09-06 12:00 PM\nupdated_at: 2026-09-06 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id, project=project))
    return d


def write_handoff(d, handoff_id, *, to="codex", gate="review", scope="s1",
                   status="approved", approval="recorded", sent="no",
                   approved_to=None, approved_gate=None, approved_scope=None,
                   owner_words="approved for the test"):
    """A handoff record written directly, in the exact shape `atlas-handoff` itself
    writes and reads — the same technique `test-agent-handoff-identity.py`'s
    `write_legacy_record()` uses, so dispatch's preflight is exercised against a record,
    not against a mock of one."""
    approved_to = to if approved_to is None else approved_to
    approved_gate = gate if approved_gate is None else approved_gate
    approved_scope = scope if approved_scope is None else approved_scope
    p = d / f"handoff-{handoff_id}.md"
    p.write_text(f"""---
handoff_id: {handoff_id}
task_id: {d.name}
status: {status}
created: 2026-09-06 12:00:00
to: {to}
gate: {gate}
scope: {scope}
source_client: unspecified
source_session_id: unspecified
current_holder: owner
next_holder: {to}
owner_action_required: none
approval: {approval}
approved_at: 2026-09-06 12:05:00
approved_gate: {approved_gate}
approved_to: {approved_to}
approved_scope: {approved_scope}
owner_words: {owner_words}
sent: {sent}
returned: none
---

# Handoff {handoff_id} — {d.name}

<!-- packet:begin -->
fixture packet
<!-- packet:end -->
""")
    return p


def write_returned_record(d, handoff_id, *, status="returned", to="codex", gate="review",
                          scope="s1", approved_scope=None, source_client="claude-code",
                          source_session="sess-r1", sent_at="2026-09-06 12:10:00",
                          received_at="2026-09-06 12:20:00",
                          received_file="/tmp/t050-s3-fixture-reply.txt",
                          returned_text="Task complete. Nothing outside scope was touched.",
                          owner_action_required="resume", next_holder="undecided"):
    """A handoff record already carrying a returned block, in the exact shape
    `atlas handoff receive` itself writes and reads: frontmatter through `sent`/`approved`,
    then `returned`/`received_*`/`returned_sha256`, then a '## 5. Returned block' section
    with the reply verbatim between the real RETURNED_BEGIN/RETURNED_END markers — the same
    technique `write_handoff()` above uses for the approve/dispatch tuple."""
    approved_scope = scope if approved_scope is None else approved_scope
    body = returned_text.strip("\n")
    digest = hashlib.sha256(body.encode()).hexdigest()
    p = d / f"handoff-{handoff_id}.md"
    p.write_text(f"""---
handoff_id: {handoff_id}
task_id: {d.name}
status: {status}
created: 2026-09-06 12:00:00
to: {to}
gate: {gate}
scope: {scope}
source_client: {source_client}
source_session_id: {source_session}
current_holder: owner
next_holder: {next_holder}
owner_action_required: {owner_action_required}
approval: recorded
approved_at: 2026-09-06 12:05:00
approved_gate: {gate}
approved_to: {to}
approved_scope: {approved_scope}
owner_words: approved for the test
sent: yes
sent_at: {sent_at}
sent_to: {to}
sent_transport: fixture-transport
payload_sha256: deadbeef
returned: attached
received_at: {received_at}
received_from: {to}
received_file: {received_file}
returned_sha256: {digest}
---

# Handoff {handoff_id} — {d.name}

<!-- packet:begin -->
fixture packet
<!-- packet:end -->

## 5. Returned block

<!-- returned:begin -->
{body}
<!-- returned:end -->
""")
    return p, digest


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def run(cmd_fn, args):
    """Call a cmd_* function like the CLI dispatcher does: capture output, capture the
    exit code from either a return value or a die()-raised SystemExit."""
    with captured() as (out, err):
        try:
            rc = cmd_fn(args)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


class FakeCompleted:
    def __init__(self, returncode=0):
        self.returncode = returncode


# =========================================================================================
with tempfile.TemporaryDirectory(prefix="t050-coordinator-") as tmp:
    root = Path(tmp)
    os.environ["ATLAS_HOME"] = str(root)
    d = make_ticket_home(root)

    # --- 1/2/3: deterministic routing off the real, shipped policy -----------------------
    t("route: real coordinator-routing.yaml resolves plan/execute/review deterministically")
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", "engine/cli"])
    chk("plan -> exit 0", rc == 0)
    chk("plan -> role planner", "role:        planner" in out)
    chk("plan -> client codex", "client:      codex" in out)

    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "execute", "--scope", "engine/cli"])
    chk("execute -> exit 0", rc == 0)
    chk("execute -> role executor", "role:        executor" in out)
    chk("execute -> client claude-code-tools-pilot", "client:      claude-code-tools-pilot" in out)

    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "review", "--scope", "engine/cli"])
    chk("review -> exit 0", rc == 0)
    chk("review -> role verifier", "role:        verifier" in out)
    chk("review -> client codex", "client:      codex" in out)

    # --- 4: unknown intent refusal --------------------------------------------------------
    t("route: unknown intent is a fail-closed refusal")
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "bogus", "--scope", "engine/cli"])
    chk("exit 2", rc == 2)
    chk("refusal names the unknown intent", "unknown intent 'bogus'" in err)
    chk("no route decision was printed", "route  T-900" not in out)

    # --- empty / malformed / traversal scope --------------------------------------------
    t("route: empty, absolute, and traversal scopes are refused")
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", ""])
    chk("empty scope refused", rc == 2 and "scope" in err)
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", "/etc/passwd"])
    chk("absolute scope refused", rc == 2 and "absolute" in err)
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", "engine/../secrets"])
    chk("traversal scope refused", rc == 2 and ".." in err)
    rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", "engine; rm -rf /"])
    chk("shell-metacharacter scope refused", rc == 2)

    # --- duplicate flags -------------------------------------------------------------------
    t("route: a flag given twice is refused, exactly like every other handoff command")
    rc, out, err = run(coordinator.cmd_route,
                       ["T-900", "--intent", "plan", "--intent", "execute", "--scope", "s"])
    chk("duplicate --intent refused", rc == 2 and "more than once" in err)

    # --- 5: unverified / undeclared transport refusal (fixture policy + fixture registry) -
    # `cmd_route`/`cmd_dispatch` each reload `cli/atlas-handoff` fresh, as its own module
    # instance, on every call (`_load_sibling`) — so a fixture transport registry has to be
    # handed to it the same way the real one is: via `ATLAS_HANDOFF_TRANSPORTS`, read at
    # that fresh module's own load time, not by mutating this test's already-loaded copy.
    t("route: a client with no verified transport is refused")
    real_policy = coordinator.POLICY
    real_transports_env = os.environ.get("ATLAS_HANDOFF_TRANSPORTS")
    try:
        fixture_policy = root / "coordinator-routing-fixture.yaml"
        fixture_policy.write_text("contract: 1\nroles:\n  stager: flaky\nintents:\n  stage: stager\n")
        fixture_transports = root / "handoff-transports-fixture.yaml"
        fixture_transports.write_text(
            "contract: 1\nroles:\n  planner: codex\ntransports:\n  flaky:\n"
            "    name: unverified fixture transport\n    binary: true\n"
            "    argv: [x]\n    stdin: packet\n    timeout: 5\n    verified: false\n")
        coordinator.POLICY = fixture_policy
        os.environ["ATLAS_HANDOFF_TRANSPORTS"] = str(fixture_transports)
        rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "stage", "--scope", "s1"])
        chk("verified: false -> exit 2 (fail closed)", rc == 2)
        chk("refusal names the client and 'not verified'", "flaky" in err and "not verified" in err)

        fixture_transports.write_text("contract: 1\nroles: {}\ntransports: {}\n")
        rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "stage", "--scope", "s1"])
        chk("client absent from the transport registry -> exit 2 (fail closed)", rc == 2)
        chk("refusal names the missing declaration", "no transport is declared" in err)

        t("route: malformed routing policy is refused, not guessed")
        fixture_policy.write_text("contract: 1\nroles:\n  stager: flaky\nintents:\n  stage: []\n")
        rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "stage", "--scope", "s1"])
        chk("non-scalar intent target -> exit 2", rc == 2 and "malformed" in err)

        fixture_policy.write_text("contract: 1\nroles:\n  someone_else: flaky\nintents:\n  stage: stager\n")
        rc, out, err = run(coordinator.cmd_route, ["T-900", "--intent", "stage", "--scope", "s1"])
        chk("intent names a role absent from 'roles' -> exit 2", rc == 2 and "no entry in 'roles'" in err)
    finally:
        coordinator.POLICY = real_policy
        if real_transports_env is None:
            os.environ.pop("ATLAS_HANDOFF_TRANSPORTS", None)
        else:
            os.environ["ATLAS_HANDOFF_TRANSPORTS"] = real_transports_env

    # --- 9: route never sends, never approves, never writes -------------------------------
    t("route: never sends, never approves, never writes to the ticket or a handoff record")
    before = sorted(p.name for p in d.iterdir())
    run(coordinator.cmd_route, ["T-900", "--intent", "plan", "--scope", "engine/cli"])
    after = sorted(p.name for p in d.iterdir())
    chk("no file was created or removed by route", before == after)
    chk("the ticket record itself was never touched", (d / "task.md").read_text().startswith("---\nkind: ticket"))

    # --- 10: dispatch requires an approved handoff -----------------------------------------
    t("dispatch: refuses a handoff that was never approved")
    write_handoff(d, "not-approved", status="waiting-owner", approval="none")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "not-approved"] + DISPATCH_LEASE_FLAGS)
    chk("exit 2", rc == 2)
    chk("refusal says not approved", "not 'approved'" in err)

    write_handoff(d, "no-approval-recorded", status="approved", approval="none")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "no-approval-recorded"] + DISPATCH_LEASE_FLAGS)
    chk("approval field not 'recorded' -> refused", rc == 2 and "no owner approval is recorded" in err)

    # --- 7: mismatched destination refusal -------------------------------------------------
    t("dispatch: refuses when the approved destination does not match the record's own")
    write_handoff(d, "mismatched-to", to="codex", approved_to="claude-code-tools-pilot")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "mismatched-to"] + DISPATCH_LEASE_FLAGS)
    chk("exit 2", rc == 2)
    chk("refusal names the destination mismatch", "mismatch on destination" in err)

    # --- 8: mismatched scope refusal --------------------------------------------------------
    t("dispatch: refuses when the approved scope does not match the record's own")
    write_handoff(d, "mismatched-scope", scope="s1", approved_scope="s2-different")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "mismatched-scope"] + DISPATCH_LEASE_FLAGS)
    chk("exit 2", rc == 2)
    chk("refusal names the scope mismatch", "mismatch on scope" in err)

    t("dispatch: refuses when the approved gate does not match the record's own")
    write_handoff(d, "mismatched-gate", gate="review", approved_gate="execute")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "mismatched-gate"] + DISPATCH_LEASE_FLAGS)
    chk("exit 2", rc == 2)
    chk("refusal names the gate mismatch", "mismatch on gate" in err)

    t("dispatch: refuses a handoff already sent")
    write_handoff(d, "already-sent", sent="yes")
    rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "already-sent"] + DISPATCH_LEASE_FLAGS)
    chk("exit 2", rc == 2)
    chk("refusal says already sent", "already sent" in err)

    t("dispatch: refuses when the destination has no verified transport")
    real_transports_env = os.environ.get("ATLAS_HANDOFF_TRANSPORTS")
    try:
        fixture_transports = root / "handoff-transports-fixture2.yaml"
        fixture_transports.write_text("contract: 1\nroles: {}\ntransports: {}\n")
        os.environ["ATLAS_HANDOFF_TRANSPORTS"] = str(fixture_transports)
        write_handoff(d, "no-transport", to="codex")
        rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "no-transport"] + DISPATCH_LEASE_FLAGS)
        chk("exit 2", rc == 2)
        chk("refusal names the missing transport", "cannot dispatch to 'codex'" in err)
    finally:
        if real_transports_env is None:
            os.environ.pop("ATLAS_HANDOFF_TRANSPORTS", None)
        else:
            os.environ["ATLAS_HANDOFF_TRANSPORTS"] = real_transports_env

    # --- 11/12: dispatch calls the existing 'atlas handoff send', once, in the foreground --
    # `subprocess` is one shared module object — `task_dir()` (inside the freshly reloaded
    # `atlas-handoff`) also calls `subprocess.run` to resolve the ticket path, via that same
    # object. A fake that intercepts *every* call would break ticket resolution itself, so
    # this only intercepts the one call shaped like the real send invocation and delegates
    # everything else (the ticket resolver included) to the real `subprocess.run` — nothing
    # here ever spawns a real client transport.
    t("dispatch: a fully approved, consistent handoff calls the existing handoff send path")
    write_handoff(d, "good", to="codex")
    # T-050-S6-R1: this is the one dispatch scenario that passes every pre-existing
    # approval-tuple check and so actually reaches the new conflict-protection gate — it
    # needs a genuinely active lease and a genuine claim covering the handoff's own scope
    # ("s1", `write_handoff`'s default), held by the exact client/session passed to dispatch.
    good_lease = coord.lease_acquire(d, "T-900", "good-client", "good-session", "good-inv",
                                     3600, "good-lease-acq")
    coord.claim_acquire(d, "T-900", good_lease["lease_id"], "s1", "good-client",
                        "good-session", "good-claim-acq")
    good_dispatch_flags = ["--lease-id", good_lease["lease_id"], "--client", "good-client",
                           "--session", "good-session"]
    calls = []
    real_subprocess_run = subprocess.run

    def fake_run(argv, **kwargs):
        if isinstance(argv, list) and len(argv) >= 2 and str(argv[0]).endswith("atlas-handoff") \
                and argv[1] == "send":
            calls.append((list(argv), kwargs))
            return FakeCompleted(0)
        return real_subprocess_run(argv, **kwargs)

    subprocess.run = fake_run
    try:
        rc, out, err = run(coordinator.cmd_dispatch, ["T-900", "good"] + good_dispatch_flags)
        chk("exit 0 (the mocked send reported success)", rc == 0)
        chk("dispatch called the send path exactly once", len(calls) == 1)
        argv = calls[0][0] if calls else []
        chk("the call targets the existing atlas-handoff binary", argv and argv[0].endswith("atlas-handoff"))
        chk("the call reuses the existing 'send' subcommand", len(argv) >= 4 and argv[1] == "send")
        chk("the call passes through the exact task id and handoff id",
            argv[-2:] == ["T-900", "good"] if len(argv) >= 2 else False)
        chk("no extra flags were invented for the transport call", len(argv) == 4)

        t("dispatch: a refused handoff never reaches the send path at all")
        calls.clear()
        run(coordinator.cmd_dispatch, ["T-900", "not-approved"] + DISPATCH_LEASE_FLAGS)
        run(coordinator.cmd_dispatch, ["T-900", "mismatched-to"] + DISPATCH_LEASE_FLAGS)
        run(coordinator.cmd_dispatch, ["T-900", "already-sent"] + DISPATCH_LEASE_FLAGS)
        chk("zero send calls across three refused dispatches", len(calls) == 0)
    finally:
        subprocess.run = real_subprocess_run

    # --- 12: no background process ---------------------------------------------------------
    t("no background process: the coordinator source contains no daemonizing construct")
    src = (CLI / "atlas-coordinator").read_text()
    banned_constructs = ["Popen(", "os.fork(", "nohup", "crontab", "daemon=True",
                          "threading.Thread(", "multiprocessing.", "while True"]
    chk("no daemonizing construct appears in cli/atlas-coordinator",
        not any(b in src for b in banned_constructs))
    chk("dispatch's one subprocess call is a single blocking subprocess.run, not Popen",
        "subprocess.run(" in src and "subprocess.Popen(" not in src)

    # --- 13: no lease/lock/queue/daemon artifacts -------------------------------------------
    t("no lease, lock, queue or daemon artifacts are ever written")
    entries = sorted(p.name for p in d.iterdir())
    # T-050-S6-R1: this same fixture ticket now also has a genuine `coordination/` directory
    # — the additive lease/claim/state layer the "good" dispatch scenario above deliberately
    # exercised (a real lease + claim, required for dispatch's new conflict-protection gate
    # to pass). That is expected, owner-authorized S6/S6-R1 state, not a lease/lock/queue/
    # daemon artifact in the sense this check is actually about — so it is the one allowed
    # extra entry; nothing else beyond it, task.md, and handoff-*.md is tolerated.
    chk("only task.md, handoff-*.md, and the S6 'coordination' directory exist in the "
        "ticket dir",
        all(n == "task.md" or n == "coordination" or
            (n.startswith("handoff-") and n.endswith(".md")) for n in entries))
    all_records_text = "\n".join((d / n).read_text() for n in entries if n.startswith("handoff-"))
    banned_vocab = ["lease_id", "lease_expires_at", "lock_id", "claimed_by", "heartbeat",
                    "queue_id", "daemon_pid", "worker_id", "scheduler"]
    chk("no lease/lock/queue/daemon vocabulary appears in any record this test wrote",
        not any(b in all_records_text for b in banned_vocab))
    runtime_dir = root / "runtime"
    # T-050-S6-R1: the "good" dispatch scenario's real claim now legitimately lives under
    # `runtime/coordination/claims/` (the existing runtime root, reused, never a new one —
    # see atlas_coordination.runtime_claims_dir()). That is the one allowed subtree; nothing
    # named like a daemon/queue/worker/scheduler artifact is tolerated anywhere under it.
    unexpected_runtime_entries = [
        str(p.relative_to(runtime_dir)) for p in runtime_dir.rglob("*")
        if "coordination" not in p.relative_to(runtime_dir).parts
    ] if runtime_dir.exists() else []
    chk("no runtime/locks, runtime/runs, or other non-S6-coordination state directory was "
        "created", not unexpected_runtime_entries)
    # Baseline for every later "no runtime state was created by <cmd>" check below: this
    # dispatch scenario is the only place in this suite that legitimately touches
    # `runtime/` (a real lease + claim, required for the new conflict-protection gate) — so
    # every subsequent prepare/review/cost check compares against *this* snapshot, not
    # against an assumption that runtime/ is empty.
    baseline_runtime_snapshot = runtime_entries(runtime_dir)

    # --- 6 (again, explicit): dispatch requires approval before send is ever attempted -----
    t("dispatch: never auto-approves — there is no code path from dispatch to 'approved'")
    src_dispatch = src[src.index("def cmd_dispatch"):src.index("CMDS = {")]
    chk("cmd_dispatch's own body never calls approve or the adapter",
        "cmd_approve" not in src_dispatch and "hoff.cmd_approve" not in src_dispatch)
    chk("cmd_dispatch's own body never assigns approval, status or writes a file",
        "p.write_text" not in src_dispatch and "'approval':" not in src_dispatch
        and "\"approval\":" not in src_dispatch)

    # =====================================================================================
    # --- T-050-S2: prepare — resolve, validate, delegate to the existing handoff prepare --
    # =====================================================================================
    protected_before = {
        "coordinator-routing.yaml": coordinator.POLICY.read_text(),
        "atlas-handoff": (CLI / "atlas-handoff").read_text(),
    }
    handoff_transports_path = Path(os.environ.get(
        "ATLAS_HANDOFF_TRANSPORTS",
        REPO / "governance" / "policies" / "handoff-transports.yaml"))
    protected_before["handoff-transports.yaml"] = handoff_transports_path.read_text()

    t("prepare: a successful call creates exactly one valid V6 handoff record")
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "plan", "--scope", "engine/cli",
                        "--source-client", "claude-code", "--source-session", "sess-001"])
    chk("exit 0", rc == 0)
    chk("stdout prints the created handoff id", "handoff id:           plan" in out)
    p_plan, text_plan, meta_plan = handoff.load_record(d, "plan")
    chk("the record file exists on disk", p_plan.is_file())
    chk("the record's own handoff_id/task_id match", meta_plan.get("handoff_id") == "plan"
        and meta_plan.get("task_id") == "T-900")

    t("prepare: identity fields are present on the record, exactly as passed")
    chk("source_client recorded verbatim", meta_plan.get("source_client") == "claude-code")
    chk("source_session_id recorded verbatim", meta_plan.get("source_session_id") == "sess-001")

    t("prepare: the selected destination matches the coordinator's own routing policy")
    real_roles, real_intents = coordinator.load_policy()
    expected_client = real_roles[real_intents["plan"]]
    chk("record's 'to' equals roles[intents['plan']] from the real policy",
        meta_plan.get("to") == expected_client)
    chk("stdout names the same destination client", f"destination client:   {expected_client}" in out)

    t("prepare: owner approval remains absent after a successful prepare")
    chk("status is 'waiting-owner', never 'approved'", meta_plan.get("status") == "waiting-owner")
    chk("approval field is 'none'", meta_plan.get("approval") == "none")
    chk("no approved_at/approved_gate/approved_to/approved_scope/owner_words was written",
        all(not str(meta_plan.get(k) or "").strip() or meta_plan.get(k) == "none"
            for k in ("approved_at", "approved_gate", "approved_to", "approved_scope", "owner_words")))

    t("prepare: never sends")
    chk("sent field is 'no'", meta_plan.get("sent") == "no")
    chk("stdout says nothing was sent", "not sent" in out)

    t("prepare: never auto-approves — dispatch is never called from inside prepare")
    src_all = (CLI / "atlas-coordinator").read_text()
    src_prepare = src_all[src_all.index("def cmd_prepare"):src_all.index("def cmd_dispatch")]
    chk("cmd_prepare's own body never calls cmd_approve or cmd_dispatch",
        "cmd_approve" not in src_prepare and "cmd_dispatch(" not in src_prepare)
    chk("cmd_prepare's own body never calls the send path",
        "cmd_send" not in src_prepare and '"send"' not in src_prepare and "'send'" not in src_prepare)
    chk("cmd_prepare's own body never writes 'approval: recorded'",
        "approval: recorded" not in src_prepare and "'recorded'" not in src_prepare)

    t("prepare: invalid intent is a fail-closed refusal, and writes nothing")
    before_files = sorted(p.name for p in d.iterdir())
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "bogus", "--scope", "engine/cli",
                        "--source-client", "claude-code", "--source-session", "sess-002"])
    chk("exit 2", rc == 2)
    chk("refusal names the unknown intent", "unknown intent 'bogus'" in err)
    chk("no handoff record was written by the refused call",
        sorted(p.name for p in d.iterdir()) == before_files)

    t("prepare: invalid scope is a fail-closed refusal")
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "/etc/passwd",
                        "--source-client", "claude-code", "--source-session", "sess-003"])
    chk("absolute scope refused", rc == 2 and "absolute" in err)
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/../secrets",
                        "--source-client", "claude-code", "--source-session", "sess-003"])
    chk("traversal scope refused", rc == 2 and ".." in err)

    t("prepare: missing source identity is a fail-closed refusal")
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/cli",
                        "--source-session", "sess-004"])
    chk("missing --source-client refused", rc == 2 and "--source-client is required" in err)
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/cli",
                        "--source-client", "claude-code"])
    chk("missing --source-session refused", rc == 2 and "--source-session is required" in err)
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/cli",
                        "--source-client", "bad client", "--source-session", "sess-005"])
    chk("malformed --source-client refused", rc == 2 and "not a client identifier" in err)
    chk("no handoff record was written by any of the missing-identity refusals",
        sorted(p.name for p in d.iterdir()) == before_files)

    t("prepare: policy mismatch — an intent with no known gate mapping is refused")
    fixture_policy2 = root / "coordinator-routing-fixture2.yaml"
    fixture_policy2.write_text("contract: 1\nroles:\n  planner: codex\nintents:\n  stage: planner\n")
    real_policy2 = coordinator.POLICY
    try:
        coordinator.POLICY = fixture_policy2
        rc, out, err = run(coordinator.cmd_prepare,
                           ["T-900", "--intent", "stage", "--scope", "engine/cli",
                            "--source-client", "claude-code", "--source-session", "sess-006"])
        chk("exit 2", rc == 2)
        chk("refusal names it a policy mismatch", "policy mismatch" in err)
    finally:
        coordinator.POLICY = real_policy2

    t("prepare: a duplicate/conflicting prepare for the same task+intent is refused, not overwritten")
    before_plan_text = p_plan.read_text()
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "plan", "--scope", "engine/tests",
                        "--source-client", "someone-else", "--source-session", "sess-999"])
    chk("exit 2", rc == 2)
    chk("refusal says the handoff already exists", "already exists" in err)
    chk("the original record was not overwritten", p_plan.read_text() == before_plan_text)

    # 'review' (not 'execute') only to keep this specific scenario independent of the
    # execute-intent scenario added below by the T-050-S2 adapter-reconciliation section —
    # both destinations ('codex' and, since the reconciliation, 'claude-code-tools-pilot')
    # are known adapter clients per `hoff.known_clients()` and work identically here.
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "review", "--scope", "engine/cli", "--id", "same-id",
                        "--source-client", "claude-code", "--source-session", "sess-007"])
    chk("first prepare with an explicit --id succeeds", rc == 0)
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "review", "--scope", "engine/tests", "--id", "same-id",
                        "--source-client", "claude-code", "--source-session", "sess-008"])
    chk("a second prepare reusing the same explicit --id is refused", rc == 2 and "already exists" in err)

    t("prepare: no runtime lease/lock/queue/daemon state is created")
    prepared_records_text = "\n".join(
        (d / n).read_text() for n in sorted(p.name for p in d.iterdir()) if n.startswith("handoff-"))
    chk("no lease/lock/queue/daemon vocabulary appears in any record prepare wrote",
        not any(b in prepared_records_text for b in
                ["lease_id", "lease_expires_at", "lock_id", "claimed_by", "heartbeat",
                 "queue_id", "daemon_pid", "worker_id", "scheduler"]))
    chk("no runtime/ state directory was created by prepare",
        runtime_entries(runtime_dir) == baseline_runtime_snapshot)

    t("prepare: protected files remain byte-for-byte unchanged")
    chk("coordinator-routing.yaml unchanged", coordinator.POLICY.read_text() == protected_before["coordinator-routing.yaml"])
    chk("cli/atlas-handoff unchanged", (CLI / "atlas-handoff").read_text() == protected_before["atlas-handoff"])
    chk("handoff-transports.yaml unchanged", handoff_transports_path.read_text() == protected_before["handoff-transports.yaml"])

    # =====================================================================================
    # --- T-050-S2 adapter reconciliation: 'claude-code-tools-pilot' is now a known client --
    # `engine/adapters/claude-code-tools-pilot/adapter.yaml` was added so `atlas-handoff`'s
    # own `known_clients()` (unmodified) recognizes the destination `coordinator-routing.yaml`
    # already resolves `execute` to, and whose transport is already `verified: true` in
    # `handoff-transports.yaml` (also unmodified). Nothing below touches either registry file,
    # `cli/atlas-handoff`, or the coordinator's own route/dispatch code.
    # =====================================================================================
    adapter_manifest_path = REPO / "adapters" / "claude-code-tools-pilot" / "adapter.yaml"
    adapter_manifest_before = adapter_manifest_path.read_text()
    handoff_transports_before_2 = handoff_transports_path.read_text()

    t("adapter reconciliation: known_clients() now recognizes 'claude-code-tools-pilot'")
    chk("the adapter manifest exists on disk", adapter_manifest_path.is_file())
    chk("hoff.known_clients() lists it", "claude-code-tools-pilot" in handoff.known_clients())
    chk("the other four pre-existing adapters are still listed too",
        {"claude-code", "codex", "cursor", "gemini", "opencode"} <= set(handoff.known_clients()))

    t("adapter reconciliation: the manifest itself parses and validates with zero errors")
    adapter_mod = _load("atlas-adapter")
    manifest_doc = adapter_mod.parse(adapter_manifest_before, str(adapter_manifest_path))
    manifest_errors, manifest_warnings = adapter_mod.validate("claude-code-tools-pilot", manifest_doc)
    chk("adapter id matches its directory name", manifest_doc.get("adapter") == "claude-code-tools-pilot")
    chk("zero validation errors", manifest_errors == [])
    chk("declares no capability (provides: {})", manifest_doc.get("provides") == {})
    chk("writes nothing (writes: [])", manifest_doc.get("writes") == [])
    chk("enforces no hook or policy (enforces: [])", manifest_doc.get("enforces") == [])

    t("adapter reconciliation: 'coordinator prepare --intent execute' now succeeds end to end")
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/cli",
                        "--source-client", "claude-code", "--source-session", "sess-exec-1"])
    chk("exit 0", rc == 0)
    chk("stdout names the created handoff id", "handoff id:           execute" in out)
    p_exec, text_exec, meta_exec = handoff.load_record(d, "execute")
    chk("the record file exists on disk", p_exec.is_file())

    t("adapter reconciliation: the record carries the exact required approval tuple")
    chk("destination is 'claude-code-tools-pilot'", meta_exec.get("to") == "claude-code-tools-pilot")
    chk("gate is 'execute'", meta_exec.get("gate") == "execute")
    chk("source_client is recorded", meta_exec.get("source_client") == "claude-code")
    chk("source_session_id is recorded", meta_exec.get("source_session_id") == "sess-exec-1")
    chk("status is 'waiting-owner'", meta_exec.get("status") == "waiting-owner")
    chk("approval is 'none'", meta_exec.get("approval") == "none")
    chk("sent is 'no'", meta_exec.get("sent") == "no")

    t("adapter reconciliation: prepare for 'execute' still never approves, sends, or dispatches")
    chk("no approved_at/approved_gate/approved_to/approved_scope/owner_words was written",
        all(not str(meta_exec.get(k) or "").strip() or meta_exec.get(k) == "none"
            for k in ("approved_at", "approved_gate", "approved_to", "approved_scope", "owner_words")))
    chk("stdout says nothing was sent, dispatch was never called", "not sent" in out and "dispatch was never called" in out)
    chk("no runtime/ state directory was created",
        runtime_entries(runtime_dir) == baseline_runtime_snapshot)
    exec_records_text = "\n".join(
        (d / n).read_text() for n in sorted(p.name for p in d.iterdir()) if n.startswith("handoff-"))
    chk("no lease/lock/queue/daemon vocabulary appears in any record on disk",
        not any(b in exec_records_text for b in
                ["lease_id", "lease_expires_at", "lock_id", "claimed_by", "heartbeat",
                 "queue_id", "daemon_pid", "worker_id", "scheduler"]))

    t("adapter reconciliation: a duplicate prepare for the same task+intent is still refused")
    rc, out, err = run(coordinator.cmd_prepare,
                       ["T-900", "--intent", "execute", "--scope", "engine/tests",
                        "--source-client", "claude-code", "--source-session", "sess-exec-2"])
    chk("exit 2", rc == 2)
    chk("refusal says the handoff already exists", "already exists" in err)
    chk("the original execute record was not overwritten", p_exec.read_text() == text_exec)

    t("adapter reconciliation: the handoff-transports.yaml entry and its 'verified' value are untouched")
    chk("handoff-transports.yaml is byte-identical to before this section ran",
        handoff_transports_path.read_text() == handoff_transports_before_2)
    chk("the real transport spec for claude-code-tools-pilot is still verified: true",
        handoff.resolve_transport("claude-code-tools-pilot")[2] is None)

    t("adapter reconciliation: cli/atlas-handoff and coordinator-routing.yaml remain unchanged")
    chk("cli/atlas-handoff unchanged", (CLI / "atlas-handoff").read_text() == protected_before["atlas-handoff"])
    chk("coordinator-routing.yaml unchanged", coordinator.POLICY.read_text() == protected_before["coordinator-routing.yaml"])
    chk("the adapter manifest itself was not modified by any of the calls above",
        adapter_manifest_path.read_text() == adapter_manifest_before)

    # =====================================================================================
    # --- T-050-S3: review — read-only report of an already-returned handoff --------------
    # `cmd_review` adds nothing to the handoff format: it reads the record with the
    # existing, unmodified `atlas-handoff.load_record()` and prints what is already there.
    # =====================================================================================
    t("review: a successful review of a returned fixture handoff")
    before_files_review = sorted(p.name for p in d.iterdir())
    task_md_before_review = (d / "task.md").read_text()
    p_returned, digest_returned = write_returned_record(
        d, "returned-cost", status="returned", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-review-1",
        sent_at="2026-09-06 13:00:00", received_at="2026-09-06 13:10:00",
        received_file="/tmp/t050-s3-cost-reply.txt",
        returned_text="Task complete. Files changed: none.\nCost: $0.032 USD.")
    rc, out, err = run(coordinator.cmd_review, ["T-900", "returned-cost"])
    chk("exit 0", rc == 0)
    chk("stdout names the task id and handoff id",
        "task id:              T-900" in out and "handoff id:           returned-cost" in out)

    t("review: identity, approval tuple, hashes, timestamps and file are all shown correctly")
    chk("source client shown", "source client:        claude-code" in out)
    chk("source session shown", "source session:       sess-review-1" in out)
    chk("destination client shown", "destination client:   codex" in out)
    chk("gate shown", "gate:                 review" in out)
    chk("approved scope shown", "approved scope:       s1" in out)
    chk("sent timestamp shown", "sent timestamp:       2026-09-06 13:00:00" in out)
    chk("received timestamp shown", "received timestamp:   2026-09-06 13:10:00" in out)
    chk("returned hash shown", f"returned hash:        {digest_returned}" in out)
    chk("returned file shown", "returned file:        /tmp/t050-s3-cost-reply.txt" in out)

    t("review: the returned text is preserved and printed verbatim")
    chk("the exact returned text appears in stdout, unaltered",
        "Task complete. Files changed: none.\nCost: $0.032 USD." in out)

    t("review: an explicit cost line is extracted and shown")
    chk("the reported cost line shows the dollar amount from the returned text",
        "cost:                 $0.032" in out)

    t("review: 'cost: not reported' when the returned text has no explicit cost")
    write_returned_record(
        d, "returned-nocost", status="reviewed", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-review-2",
        returned_text="Task complete. Nothing else to report.")
    rc, out, err = run(coordinator.cmd_review, ["T-900", "returned-nocost"])
    chk("exit 0 (status 'reviewed' is accepted, same as 'returned')", rc == 0)
    chk("cost is reported as not reported", "cost:                 not reported" in out)

    t("review: transport budget is shown separately from the reported actual cost")
    write_returned_record(
        d, "returned-budget", status="returned", to="claude-code-tools-pilot", gate="execute",
        scope="engine/cli", source_client="claude-code", source_session="sess-review-3",
        returned_text="Task complete. Actual cost: $0.021.")
    rc, out, err = run(coordinator.cmd_review, ["T-900", "returned-budget"])
    chk("exit 0", rc == 0)
    real_spec, _binary, _unavailable = handoff.resolve_transport("claude-code-tools-pilot")
    real_budget = None
    for i, a in enumerate(real_spec.get("argv") or []):
        if a == "--max-budget-usd" and i + 1 < len(real_spec["argv"]):
            real_budget = real_spec["argv"][i + 1]
    chk("the real transport declares a budget to compare against", real_budget is not None)
    chk("the transport budget line shows the transport's own declared cap",
        f"transport budget:     {real_budget}" in out)
    chk("the reported cost line shows the different, explicitly-stated actual cost",
        "cost:                 $0.021" in out)
    chk("the two numbers are shown as different values, never conflated",
        real_budget != "0.021")

    t("review: refuses draft, waiting-owner, approved, and sent handoffs")
    for bad_status in ("draft", "waiting-owner", "approved", "sent"):
        write_handoff(d, f"status-{bad_status}", status=bad_status,
                      approval="none" if bad_status in ("draft", "waiting-owner") else "recorded",
                      sent="yes" if bad_status == "sent" else "no")
        rc, out, err = run(coordinator.cmd_review, ["T-900", f"status-{bad_status}"])
        chk(f"review of a {bad_status!r} handoff is refused (exit 2)", rc == 2)
        chk(f"refusal for {bad_status!r} names 'returned' or 'reviewed' as required",
            "'returned' or 'reviewed'" in err)

    t("review never writes any file")
    after_files_review = sorted(p.name for p in d.iterdir())
    chk("no file was created or removed by any review call above",
        set(after_files_review) - set(before_files_review) ==
        {"handoff-returned-cost.md", "handoff-returned-nocost.md", "handoff-returned-budget.md",
         "handoff-status-draft.md", "handoff-status-waiting-owner.md",
         "handoff-status-approved.md", "handoff-status-sent.md"})
    chk("the returned-cost record is byte-identical to what the fixture wrote",
        (d / "handoff-returned-cost.md").read_text() ==
        p_returned.read_text())

    t("review never changes handoff status or any other field on the record")
    _, _, meta_after_review = handoff.load_record(d, "returned-cost")
    chk("status is still 'returned'", meta_after_review.get("status") == "returned")
    chk("returned field is still 'attached'", meta_after_review.get("returned") == "attached")

    t("review never marks the ticket done")
    chk("task.md is byte-identical to before every review call above",
        (d / "task.md").read_text() == task_md_before_review)

    t("review never calls approve, send, dispatch, or receive, and never picks a next hop")
    src_review = src_all[src_all.index("def cmd_review"):]
    chk("cmd_review's own body never calls cmd_approve",
        "cmd_approve" not in src_review and "hoff.cmd_approve" not in src_review)
    chk("cmd_review's own body never calls cmd_send or the send path",
        "cmd_send" not in src_review and '"send"' not in src_review and "'send'" not in src_review)
    chk("cmd_review's own body never calls cmd_dispatch",
        "cmd_dispatch(" not in src_review)
    chk("cmd_review's own body never calls cmd_receive",
        "cmd_receive" not in src_review and "hoff.cmd_receive" not in src_review)
    chk("cmd_review's own body never writes a file (no .write_text anywhere in it)",
        "write_text" not in src_review)
    chk("cmd_review's own body never writes a 'next_holder' field",
        "next_holder\":" not in src_review and "'next_holder':" not in src_review)

    t("review: no lease/lock/queue/daemon vocabulary and no runtime state directory")
    review_records_text = "\n".join(
        (d / n).read_text() for n in sorted(p.name for p in d.iterdir()) if n.startswith("handoff-"))
    chk("no lease/lock/queue/daemon vocabulary appears in any record on disk",
        not any(b in review_records_text for b in
                ["lease_id", "lease_expires_at", "lock_id", "claimed_by", "heartbeat",
                 "queue_id", "daemon_pid", "worker_id", "scheduler"]))
    chk("no runtime/ state directory was created by review",
        runtime_entries(runtime_dir) == baseline_runtime_snapshot)

    t("review: protected files remain byte-for-byte unchanged")
    chk("coordinator-routing.yaml unchanged", coordinator.POLICY.read_text() == protected_before["coordinator-routing.yaml"])
    chk("cli/atlas-handoff unchanged", (CLI / "atlas-handoff").read_text() == protected_before["atlas-handoff"])
    chk("handoff-transports.yaml unchanged", handoff_transports_path.read_text() == protected_before["handoff-transports.yaml"])

    # =====================================================================================
    # --- T-050-S4: cost — deterministic, read-only cost observability -------------------
    # `cmd_cost` adds nothing to the handoff format: every field it prints is read from an
    # existing record's own frontmatter, its own returned block, or the existing verified
    # transport registry. It never approves, sends, dispatches, receives, or estimates a
    # cost — this section checks that as thoroughly as it checks the reports themselves.
    # =====================================================================================
    import json as _json

    t("cost: one returned handoff with an explicit reported cost")
    before_files_cost = sorted(p.name for p in d.iterdir())
    task_md_before_cost = (d / "task.md").read_text()
    write_returned_record(
        d, "cost-reported", status="returned", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-cost-1",
        sent_at="2026-09-06 14:00:00", received_at="2026-09-06 14:10:00",
        returned_text="Task complete. Cost: $0.045 USD.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-reported"])
    chk("exit 0", rc == 0)
    chk("task id shown", "task id:              T-900" in out)
    chk("handoff id shown", "handoff id:           cost-reported" in out)
    chk("source client shown", "source client:        claude-code" in out)
    chk("source session shown", "source session:       sess-cost-1" in out)
    chk("destination client shown", "destination client:   codex" in out)
    chk("gate shown", "gate:                 review" in out)
    chk("status shown", "status:               returned" in out)
    chk("sent timestamp shown", "sent timestamp:       2026-09-06 14:00:00" in out)
    chk("received timestamp shown", "received timestamp:   2026-09-06 14:10:00" in out)
    chk("invocation count is 1 (one send occurred)", "invocation count:     1" in out)
    chk("actual cost shown", "actual cost:          $0.045" in out)
    chk("cost status is 'reported'", "cost status:          reported" in out)

    t("cost: one returned handoff with no explicit cost")
    write_returned_record(
        d, "cost-none", status="returned", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-cost-2",
        returned_text="Task complete. Nothing else to report.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-none"])
    chk("exit 0", rc == 0)
    chk("actual cost is 'not reported'", "actual cost:          not reported" in out)
    chk("cost status is 'not_reported'", "cost status:          not_reported" in out)
    chk("reduction signal is 'cost_unreported'", "reduction signal:     cost_unreported" in out)

    t("cost: transport budget is displayed, and separately from actual cost")
    write_returned_record(
        d, "cost-budget-under", status="returned", to="claude-code-tools-pilot", gate="execute",
        scope="engine/cli", source_client="claude-code", source_session="sess-cost-3",
        returned_text="Task complete. Actual cost: $0.02.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-budget-under"])
    chk("exit 0", rc == 0)
    chk("transport budget shown as the declared cap 0.10",
        "transport budget:     0.10" in out)
    chk("actual cost shown as the different, explicitly-stated $0.02",
        "actual cost:          $0.02" in out)

    t("cost: within_budget only when both actual cost and budget are valid, and actual <= budget")
    chk("reduction signal is 'within_budget'", "reduction signal:     within_budget" in out)

    t("cost: over_budget only when both actual cost and budget are valid, and actual exceeds budget")
    write_returned_record(
        d, "cost-budget-over", status="returned", to="claude-code-tools-pilot", gate="execute",
        scope="engine/cli", source_client="claude-code", source_session="sess-cost-4",
        returned_text="Task complete. Actual cost: $5.00.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-budget-over"])
    chk("exit 0", rc == 0)
    chk("transport budget still shown as the declared cap 0.10",
        "transport budget:     0.10" in out)
    chk("actual cost shown as $5.00", "actual cost:          $5.00" in out)
    chk("reduction signal is 'over_budget'", "reduction signal:     over_budget" in out)

    t("cost: a reported cost with no declared transport budget never claims a saving")
    write_returned_record(
        d, "cost-no-budget", status="returned", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-cost-5",
        returned_text="Task complete. Cost: $0.50.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-no-budget"])
    chk("exit 0", rc == 0)
    chk("codex declares no transport budget", "transport budget:     not declared" in out)
    chk("reduction signal is 'budget_unavailable', never within_budget/over_budget",
        "reduction signal:     budget_unavailable" in out)

    t("cost: two conflicting cost mentions in the same returned text is 'invalid_report', never a guess")
    write_returned_record(
        d, "cost-conflict", status="returned", to="codex", gate="review", scope="s1",
        source_client="claude-code", source_session="sess-cost-6",
        returned_text="Task complete. Cost: $1.00. Actual cost: $2.00.")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-conflict"])
    chk("exit 0 (an invalid report is still reported, not refused)", rc == 0)
    chk("cost status is 'invalid_report'", "cost status:          invalid_report" in out)
    chk("reduction signal is 'cost_unreported' for an invalid report too",
        "reduction signal:     cost_unreported" in out)

    t("cost: invocation count is 0 for a handoff that was never sent")
    write_handoff(d, "cost-never-sent", status="waiting-owner", approval="none", sent="no")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-never-sent"])
    chk("exit 0", rc == 0)
    chk("invocation count is 0 (no send occurred)", "invocation count:     0" in out)
    chk("actual cost is 'not reported' — no returned block exists at all",
        "actual cost:          not reported" in out)

    t("cost: invocation count is 1 for a handoff that was sent exactly once")
    chk("the earlier 'cost-reported' handoff already asserted invocation count 1 above", True)

    t("cost: an ambiguous/contradictory send audit is a refusal, never a guessed count")
    p_ambig = d / "handoff-cost-ambiguous.md"
    p_ambig.write_text("""---
handoff_id: cost-ambiguous
task_id: T-900
status: approved
created: 2026-09-06 12:00:00
to: codex
gate: review
scope: s1
source_client: claude-code
source_session_id: sess-cost-ambig
current_holder: owner
next_holder: codex
owner_action_required: none
approval: recorded
approved_at: 2026-09-06 12:05:00
approved_gate: review
approved_to: codex
approved_scope: s1
owner_words: approved for the test
sent: yes
returned: none
---

# Handoff cost-ambiguous — T-900

<!-- packet:begin -->
fixture packet
<!-- packet:end -->
""")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-ambiguous"])
    chk("exit 2 (refused, not a guessed 0 or 1)", rc == 2)
    chk("refusal names the ambiguous/contradictory audit",
        "ambiguous or contradictory send audit" in err)
    chk("nothing was printed as a report", "cost  T-900" not in out)

    t("cost: a malformed record (missing a required field) fails closed")
    p_malformed = d / "handoff-cost-malformed.md"
    p_malformed.write_text("""---
handoff_id: cost-malformed
task_id: T-900
to: codex
gate: review
scope: s1
sent: no
returned: none
---

# Handoff cost-malformed — T-900

<!-- packet:begin -->
fixture packet
<!-- packet:end -->
""")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-malformed"])
    chk("exit 2 (refused, not reported with blanks)", rc == 2)
    chk("refusal names the missing field", "missing" in err and "status" in err)

    t("cost: an unknown --handoff id is refused, exactly like review/dispatch")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "does-not-exist"])
    chk("exit 4 (not found)", rc == 4)

    t("cost: task-wide aggregation across every handoff belonging to the task")
    # A dedicated, otherwise-empty ticket rather than `d`: `d` accumulates fixture handoffs
    # from every S1-S3 section above, including some deliberately malformed/ambiguous ones
    # written for *those* sections' own refusal tests — aggregation over the whole task is
    # tested here against a clean set this section controls end to end.
    agg_d = make_ticket_home(root, ticket_id="T-902")
    write_returned_record(agg_d, "agg-1", status="returned", to="codex", gate="review",
                          scope="s1", source_client="claude-code", source_session="sess-agg-1",
                          returned_text="Task complete. Cost: $0.01.")
    write_handoff(agg_d, "agg-2", status="waiting-owner", approval="none", sent="no")
    rc, out, err = run(coordinator.cmd_cost, ["T-902"])
    chk("exit 0", rc == 0)
    chk("both handoff records on the task appear in the aggregated report",
        "handoff id:           agg-1" in out and "handoff id:           agg-2" in out)
    chk("more than one handoff id appears (this is a real aggregation, not a single record)",
        out.count("handoff id:           ") == 2)

    t("cost: --handoff filters the report down to exactly one handoff")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-reported"])
    chk("exit 0", rc == 0)
    chk("only the named handoff id appears", out.count("handoff id:           ") == 1)
    chk("the named handoff's id is the one shown", "handoff id:           cost-reported" in out)

    t("cost: --json produces valid, deterministic JSON with the documented field order")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-reported", "--json"])
    chk("exit 0", rc == 0)
    parsed = None
    try:
        parsed = _json.loads(out)
    except _json.JSONDecodeError:
        pass
    chk("stdout parses as valid JSON", parsed is not None)
    chk("top-level task_id is correct", parsed is not None and parsed.get("task_id") == "T-900")
    chk("handoffs is a list of exactly one report", parsed is not None and len(parsed.get("handoffs", [])) == 1)
    if parsed is not None:
        h0 = parsed["handoffs"][0]
        chk("handoff_id is correct", h0.get("handoff_id") == "cost-reported")
        chk("cost_status is 'reported'", h0.get("cost_status") == "reported")
        chk("invocation_count is an int 1, not a string", h0.get("invocation_count") == 1 and
            isinstance(h0.get("invocation_count"), int))
        chk("actual_cost carries the explicit dollar amount", h0.get("actual_cost") == "$0.045")
        chk("reduction_signal is present", "reduction_signal" in h0)
    # Fixed key order in the raw JSON text itself, not just after parsing — "stable key
    # ordering" means the serialized bytes are ordered, not merely round-trippable.
    key_order = ["task_id", "handoff_id", "source_client", "source_session_id",
                "destination_client", "gate", "status", "sent_at", "received_at",
                "invocation_count", "transport_budget", "actual_cost", "cost_status",
                "reduction_signal"]
    positions = [out.index(f'"{k}"') for k in key_order[1:]]
    chk("every report key appears in the documented fixed order in the raw JSON text",
        positions == sorted(positions))
    rc2, out2, err2 = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-reported", "--json"])
    chk("--json output is byte-identical across repeated calls (deterministic)", out == out2)

    t("cost: human-readable field order is fixed")
    rc, out, err = run(coordinator.cmd_cost, ["T-900", "--handoff", "cost-reported"])
    human_order = ["task id:", "handoff id:", "source client:", "source session:",
                  "destination client:", "gate:", "status:", "sent timestamp:",
                  "received timestamp:", "invocation count:", "transport budget:",
                  "actual cost:", "cost status:", "reduction signal:"]
    human_positions = [out.index(label) for label in human_order]
    chk("every human-readable field appears in the documented fixed order",
        human_positions == sorted(human_positions))

    t("cost: --handoff or --json given twice is refused")
    rc, out, err = run(coordinator.cmd_cost,
                       ["T-900", "--handoff", "cost-reported", "--handoff", "cost-none"])
    chk("duplicate --handoff refused", rc == 2 and "more than once" in err)
    rc, out, err = run(coordinator.cmd_cost,
                       ["T-900", "--handoff", "cost-reported", "--json", "--json"])
    chk("duplicate --json refused", rc == 2 and "more than once" in err)

    t("cost: an empty task result fails clearly and without writing")
    empty_d = make_ticket_home(root, ticket_id="T-901")
    before_files_empty = sorted(p.name for p in empty_d.iterdir())
    rc, out, err = run(coordinator.cmd_cost, ["T-901"])
    chk("exit 4 (no handoff records for this task)", rc == 4)
    chk("the refusal says clearly there is nothing to report",
        "no handoff records exist" in err)
    chk("nothing was written to the empty task's directory",
        sorted(p.name for p in empty_d.iterdir()) == before_files_empty)

    t("cost never writes any file")
    after_files_cost = sorted(p.name for p in d.iterdir())
    chk("no file was created or removed by any cost call above beyond the fixtures created",
        (set(after_files_cost) - set(before_files_cost)) ==
        {"handoff-cost-reported.md", "handoff-cost-none.md", "handoff-cost-budget-under.md",
         "handoff-cost-budget-over.md", "handoff-cost-no-budget.md", "handoff-cost-conflict.md",
         "handoff-cost-never-sent.md", "handoff-cost-ambiguous.md", "handoff-cost-malformed.md"})

    t("cost never marks the ticket done")
    chk("task.md is byte-identical to before every cost call above",
        (d / "task.md").read_text() == task_md_before_cost)

    t("cost never calls approve, send, dispatch, or receive")
    src_cost = src_all[src_all.index("def cmd_cost"):]
    chk("cmd_cost's own body never calls cmd_approve",
        "cmd_approve" not in src_cost and "hoff.cmd_approve" not in src_cost)
    chk("cmd_cost's own body never calls cmd_send",
        "cmd_send" not in src_cost)
    chk("cmd_cost's own body never calls cmd_dispatch",
        "cmd_dispatch(" not in src_cost)
    chk("cmd_cost's own body never calls cmd_receive",
        "cmd_receive" not in src_cost and "hoff.cmd_receive" not in src_cost)
    src_cost_section = src_all[src_all.index("def _returned_text_maybe"):]
    chk("the whole cost implementation (helpers + cmd_cost) never writes a file",
        "write_text" not in src_cost_section)

    t("cost: no lease/lock/queue/daemon vocabulary and no runtime state directory")
    cost_records_text = "\n".join(
        (d / n).read_text() for n in sorted(p.name for p in d.iterdir()) if n.startswith("handoff-"))
    chk("no lease/lock/queue/daemon vocabulary appears in any record on disk",
        not any(b in cost_records_text for b in
                ["lease_id", "lease_expires_at", "lock_id", "claimed_by", "heartbeat",
                 "queue_id", "daemon_pid", "worker_id", "scheduler"]))
    chk("no runtime/ state directory was created by cost",
        runtime_entries(runtime_dir) == baseline_runtime_snapshot)

    t("cost: protected files remain byte-for-byte unchanged")
    chk("coordinator-routing.yaml unchanged", coordinator.POLICY.read_text() == protected_before["coordinator-routing.yaml"])
    chk("cli/atlas-handoff unchanged", (CLI / "atlas-handoff").read_text() == protected_before["atlas-handoff"])
    chk("handoff-transports.yaml unchanged", handoff_transports_path.read_text() == protected_before["handoff-transports.yaml"])

print(f"\n{passed} passed, {failed} failed")

# =========================================================================================
# --- 14: core/cli/atlas and engine/cli/atlas coordinator parity, as real subprocesses -----
t("core and engine 'atlas coordinator route' resolve identically, as real subprocesses")


def real_ticket_env():
    """A fresh fixture ticket, because this section runs real processes rather than
    in-process calls and must not race the sections above that mutated ATLAS_HOME state."""
    tmp = tempfile.mkdtemp(prefix="t050-parity-")
    root = Path(tmp)
    make_ticket_home(root)
    env = dict(os.environ)
    env["ATLAS_HOME"] = str(root)
    # engine/governance/policies/handoff-transports.yaml is product code (lives
    # in the repo, not the private workspace) — core/ is a separate, still-partial
    # skeleton tree (AIOS-020) with no internal/ directory of its own yet, so its own
    # copy of atlas-handoff would otherwise fall back to a path that doesn't exist there.
    # Point both processes at the SAME current registry so this section proves route
    # decisions agree, not tree completeness of an admittedly unfinished skeleton.
    env["ATLAS_HANDOFF_TRANSPORTS"] = str(REPO / "governance" / "policies" /
                                          "handoff-transports.yaml")
    return env


def normalize(text):
    # Strip the one line that legitimately differs: the resolved transport binary path,
    # which depends on each copy's own PATH-derived shutil.which() result but names the
    # same client either way.
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("transport:"))


env = real_ticket_env()
parity_root = Path(env["ATLAS_HOME"])
core_atlas = REPO.parent / "core" / "cli" / "atlas"
engine_atlas = CLI / "atlas"
results = {}
for intent in ("plan", "execute", "review"):
    core_r = subprocess.run([str(core_atlas), "coordinator", "route", "T-900",
                            "--intent", intent, "--scope", "s1"],
                           capture_output=True, text=True, env=env)
    engine_r = subprocess.run([str(engine_atlas), "coordinator", "route", "T-900",
                              "--intent", intent, "--scope", "s1"],
                             capture_output=True, text=True, env=env)
    results[intent] = (core_r, engine_r)
    chk(f"core and engine both exit 0 for intent={intent}",
        core_r.returncode == 0 and engine_r.returncode == 0)
    chk(f"core and engine print the same route decision for intent={intent}",
        normalize(core_r.stdout) == normalize(engine_r.stdout))

# --- 15: the canonical `atlas` entry point dispatches coordinator too, as a real subprocess
t("canonical 'engine/cli/atlas coordinator route' works, not just the atlas alias")
atlas_bin = CLI / "atlas"
before_entries = sorted(p.name for p in (parity_root / "projects" / "demo" / "tickets" / "T-900").iterdir())
runtime_before = (parity_root / "runtime")
runtime_existed_before = runtime_before.exists()
atlas_r = subprocess.run([str(atlas_bin), "coordinator", "route", "T-900",
                         "--intent", "execute", "--scope", "s1"],
                        capture_output=True, text=True, env=env)
chk("atlas coordinator route exits 0", atlas_r.returncode == 0)
chk("output shows role: executor", "role:        executor" in atlas_r.stdout)
chk("output shows client: claude-code-tools-pilot",
    "client:      claude-code-tools-pilot" in atlas_r.stdout)
chk("output never claims anything was sent or approved",
    "sent:" not in atlas_r.stdout.lower() and "approved  " not in atlas_r.stdout.lower())
after_entries = sorted(p.name for p in (parity_root / "projects" / "demo" / "tickets" / "T-900").iterdir())
chk("no file was created or removed in the ticket dir", before_entries == after_entries)
chk("no runtime/ state directory was created by this call",
    (not runtime_before.exists()) if not runtime_existed_before
    else not any(runtime_before.rglob("*")))
execute_core_r, execute_engine_r = results["execute"]
chk("core, engine atlas, and the canonical atlas entry point all agree for intent=execute",
    normalize(atlas_r.stdout) == normalize(execute_engine_r.stdout) == normalize(execute_core_r.stdout))

# --- 16: coordinator review parity across core, engine atlas, and canonical atlas ---------
t("core, engine atlas, and canonical atlas 'coordinator review' agree, as real subprocesses")
parity_ticket_dir = parity_root / "projects" / "demo" / "tickets" / "T-900"
parity_entries_before = sorted(p.name for p in parity_ticket_dir.iterdir())
write_returned_record(parity_ticket_dir, "parity-review", status="returned", to="codex",
                      gate="review", scope="s1", source_client="claude-code",
                      source_session="sess-parity-1",
                      returned_text="Parity check complete. Cost: $0.010.")
core_review_r = subprocess.run([str(core_atlas), "coordinator", "review", "T-900", "parity-review"],
                               capture_output=True, text=True, env=env)
engine_review_r = subprocess.run([str(engine_atlas), "coordinator", "review", "T-900", "parity-review"],
                                 capture_output=True, text=True, env=env)
atlas_review_r = subprocess.run([str(atlas_bin), "coordinator", "review", "T-900", "parity-review"],
                                capture_output=True, text=True, env=env)
chk("core 'atlas coordinator review' exits 0", core_review_r.returncode == 0)
chk("engine 'atlas coordinator review' exits 0", engine_review_r.returncode == 0)
chk("canonical 'atlas coordinator review' exits 0", atlas_review_r.returncode == 0)
chk("core, engine atlas, and canonical atlas print the identical review report",
    core_review_r.stdout == engine_review_r.stdout == atlas_review_r.stdout)
chk("the report shows the explicit reported cost",
    "cost:                 $0.010" in core_review_r.stdout)
chk("review as a real subprocess never approves or sends",
    "approval:" not in core_review_r.stdout.lower() and "sent:      yes" not in core_review_r.stdout)
parity_entries_after = sorted(p.name for p in parity_ticket_dir.iterdir())
chk("review wrote no file beyond the one fixture record created by the test itself",
    set(parity_entries_after) - set(parity_entries_before) == {"handoff-parity-review.md"})

t("canonical atlas 'coordinator review' refuses a handoff that has not been returned")
write_handoff(parity_ticket_dir, "not-yet-sent", status="waiting-owner", approval="none")
atlas_review_bad = subprocess.run([str(atlas_bin), "coordinator", "review", "T-900", "not-yet-sent"],
                                  capture_output=True, text=True, env=env)
chk("review of a 'waiting-owner' handoff is refused (exit 2) through the canonical atlas entry point",
    atlas_review_bad.returncode == 2)
chk("the refusal names 'returned' or 'reviewed' as required",
    "'returned' or 'reviewed'" in atlas_review_bad.stderr)

# --- 17: coordinator cost parity across core, engine atlas, and canonical atlas -----------
t("core, engine atlas, and canonical atlas 'coordinator cost' agree, as real subprocesses")
parity_entries_before_cost = sorted(p.name for p in parity_ticket_dir.iterdir())
write_returned_record(parity_ticket_dir, "parity-cost", status="returned", to="codex",
                      gate="review", scope="s1", source_client="claude-code",
                      source_session="sess-parity-cost",
                      returned_text="Parity check complete. Cost: $0.015.")
core_cost_r = subprocess.run([str(core_atlas), "coordinator", "cost", "T-900", "--handoff", "parity-cost"],
                             capture_output=True, text=True, env=env)
engine_cost_r = subprocess.run([str(engine_atlas), "coordinator", "cost", "T-900", "--handoff", "parity-cost"],
                               capture_output=True, text=True, env=env)
atlas_cost_r = subprocess.run([str(atlas_bin), "coordinator", "cost", "T-900", "--handoff", "parity-cost"],
                              capture_output=True, text=True, env=env)
chk("core 'atlas coordinator cost' exits 0", core_cost_r.returncode == 0)
chk("engine 'atlas coordinator cost' exits 0", engine_cost_r.returncode == 0)
chk("canonical 'atlas coordinator cost' exits 0", atlas_cost_r.returncode == 0)
chk("core, engine atlas, and canonical atlas print the identical cost report",
    core_cost_r.stdout == engine_cost_r.stdout == atlas_cost_r.stdout)
chk("the report shows the explicit reported cost",
    "actual cost:          $0.015" in core_cost_r.stdout)
chk("cost as a real subprocess never approves or sends",
    "approval:" not in core_cost_r.stdout.lower() and "sent:      yes" not in core_cost_r.stdout)
parity_entries_after_cost = sorted(p.name for p in parity_ticket_dir.iterdir())
chk("cost wrote no file beyond the one fixture record created by the test itself",
    set(parity_entries_after_cost) - set(parity_entries_before_cost) == {"handoff-parity-cost.md"})

t("core, engine atlas, and canonical atlas 'coordinator cost --json' agree, as real subprocesses")
core_cost_json_r = subprocess.run([str(core_atlas), "coordinator", "cost", "T-900",
                                   "--handoff", "parity-cost", "--json"],
                                  capture_output=True, text=True, env=env)
engine_cost_json_r = subprocess.run([str(engine_atlas), "coordinator", "cost", "T-900",
                                     "--handoff", "parity-cost", "--json"],
                                    capture_output=True, text=True, env=env)
atlas_cost_json_r = subprocess.run([str(atlas_bin), "coordinator", "cost", "T-900",
                                    "--handoff", "parity-cost", "--json"],
                                   capture_output=True, text=True, env=env)
chk("all three exit 0 for --json", core_cost_json_r.returncode == 0 and
    engine_cost_json_r.returncode == 0 and atlas_cost_json_r.returncode == 0)
chk("all three print byte-identical JSON",
    core_cost_json_r.stdout == engine_cost_json_r.stdout == atlas_cost_json_r.stdout)
import json as _json_parity
parity_parsed = _json_parity.loads(core_cost_json_r.stdout)
chk("the parsed JSON carries the expected handoff_id and cost_status",
    parity_parsed["handoffs"][0]["handoff_id"] == "parity-cost" and
    parity_parsed["handoffs"][0]["cost_status"] == "reported")

t("canonical atlas 'coordinator cost' fails clearly on a task with no handoff records")
cost_empty_root = Path(tempfile.mkdtemp(prefix="t050-s4-empty-"))
make_ticket_home(cost_empty_root, ticket_id="T-903")
cost_empty_env = dict(os.environ)
cost_empty_env["ATLAS_HOME"] = str(cost_empty_root)
atlas_cost_empty = subprocess.run([str(atlas_bin), "coordinator", "cost", "T-903"],
                                  capture_output=True, text=True, env=cost_empty_env)
chk("exit 4 through the canonical atlas entry point", atlas_cost_empty.returncode == 4)
chk("the refusal says clearly there is nothing to report",
    "no handoff records exist" in atlas_cost_empty.stderr)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
