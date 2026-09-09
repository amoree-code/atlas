#!/usr/bin/env python3
"""tests/test-coordinator-apply.py — T-103: Agentic Revision Lease and Conflict Gate.

Proves `atlas_coordination.apply_result` / `atlas coordinator apply` — the one new
enforcement entry point T-103 adds on top of the existing lease/claim mechanism
(`cli/atlas_coordination.py`, already exercised by `dispatch`/`finalize` and by
`tests/test-coordinator-conflict-protection.py`). Nothing here re-tests claim/lease
acquisition itself in depth — that suite already does, extensively — this one proves the
NEW composition: a writer must hold a matching claim before applying, a stale base
revision is refused before anything is written, a conflicting writer is refused a claim in
the first place, every decision (conflict, staleness, applied, failed) is recorded in the
ticket's own `coordination/audit.log`, and the claim is released on every path out of
`apply_result` where one was actually held — success, a stale refusal, or the callback
itself raising — never swallowed; a caller with no valid claim to begin with is refused
without ever pretending to release one. (A stale-refusal branch that returned before
releasing its claim was a bug found and fixed after the first version of this file shipped
— see the two "a stale result" scenarios below, which pin the fix down explicitly.)

Every scenario runs against a throwaway ATLAS_HOME fixture, exactly like
test-coordinator-conflict-protection.py's own `make_ticket_home()`. Nothing here touches
the real workspace.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli"

G, R, D, X = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = R = D = X = ""
passed = failed = 0


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
        f"under_test_apply_{name.replace('-', '_').replace('.', '_')}",
        importlib.machinery.SourceFileLoader(
            f"under_test_apply_{name.replace('-', '_').replace('.', '_')}", str(CLI / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


coordinator = _load("atlas-coordinator")
coord = _load("atlas_coordination.py")

EMPTY = coord.EMPTY_REVISION


def make_ticket_home(root, project="demo", ticket_id="T-900"):
    # `canonicalize_path`/`atlas_home()` resolve claim paths against $ATLAS_HOME globally —
    # independent of the `task_dir` passed to lease/claim calls — so every fixture MUST set
    # this before touching claims/apply, exactly like test-coordinator-conflict-protection.py's
    # own `new_home()`. Skipping this is not a cosmetic gap: it silently resolves claims
    # against the real ~/atlas instead of the throwaway fixture.
    os.environ["ATLAS_HOME"] = str(root)
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for T-103 apply tests\nstate: active\n"
        "project: {project}\nopened_at: 2026-09-08 12:00 PM\nupdated_at: 2026-09-08 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id, project=project))
    return d


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def audit_ops(d, op):
    p = coord.coordination_dir(d) / "audit.log"
    if not p.is_file():
        return []
    return [json.loads(l) for l in p.read_text().splitlines() if json.loads(l)["op"] == op]


def acquire_lease(d, task_id, client="c1", session="s1", inv="i1", key=None):
    key = key or f"lease-{task_id}-{client}-{session}"
    return coord.lease_acquire(d, task_id, client, session, inv, 300, key)


def acquire_claim(d, task_id, lease_id, path, client="c1", session="s1", key=None):
    key = key or f"claim-{task_id}-{path}-{client}"
    return coord.claim_acquire(d, task_id, lease_id, path, client, session, key)


# =========================================================================================
t("readers coexist — nothing about this mechanism ever gates a plain read")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-901")
    lease = acquire_lease(d, "T-901")
    claim = acquire_claim(d, "T-901", lease["lease_id"], "f.txt")
    coord.apply_result(d, "T-901", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                       lambda: Path(claim["path"]).write_text("v1"), "apply-901")
    results = []

    def reader():
        results.append(Path(claim["path"]).read_text())

    threads = [threading.Thread(target=reader) for _ in range(5)]
    for th in threads: th.start()
    for th in threads: th.join()
    chk("five concurrent readers all read the same content with no error, no lock touched",
        results == ["v1"] * 5)

# =========================================================================================
t("two writers on different scopes proceed independently")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-902")
    lease = acquire_lease(d, "T-902")
    claim_a = acquire_claim(d, "T-902", lease["lease_id"], "a.txt", key="claim-a")
    claim_b = acquire_claim(d, "T-902", lease["lease_id"], "b.txt", key="claim-b")
    ra = coord.apply_result(d, "T-902", lease["lease_id"], "a.txt", "c1", "s1", EMPTY,
                            lambda: Path(claim_a["path"]).write_text("A"), "apply-a")
    rb = coord.apply_result(d, "T-902", lease["lease_id"], "b.txt", "c1", "s1", EMPTY,
                            lambda: Path(claim_b["path"]).write_text("B"), "apply-b")
    chk("both applied", Path(claim_a["path"]).read_text() == "A"
        and Path(claim_b["path"]).read_text() == "B")
    chk("each carries its own new_revision, independent of the other",
        ra["new_revision"] != rb["new_revision"])

# =========================================================================================
t("a second writer on the same scope is refused a claim — deterministic conflict reason")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-903")
    d_b = make_ticket_home(home, ticket_id="T-903b")
    lease_a = acquire_lease(d, "T-903", client="writer-a", session="sa", key="lease-a")
    claim_a = acquire_claim(d, "T-903", lease_a["lease_id"], "shared.txt", client="writer-a",
                            session="sa")
    lease_b = acquire_lease(d_b, "T-903b", client="writer-b", session="sb", key="lease-b")
    try:
        acquire_claim(d_b, "T-903b", lease_b["lease_id"], "shared.txt", client="writer-b",
                      session="sb")
        chk("the second writer's claim attempt raised", False)
    except coord.CoordinationError as e:
        chk("refused, deterministic and names the current holder",
            "already claimed by writer-a/sa" in str(e))
    conflicts = audit_ops(d_b, "claim_conflict")
    chk("conflict evidence recorded in the audit log",
        len(conflicts) == 1 and conflicts[0]["requested_by"] == "writer-b/sb"
        and conflicts[0]["held_by"] == "writer-a/sa" and conflicts[0]["decision"] == "deny")

t("a writer that never held a claim is refused by apply_result itself, downstream never runs")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-904")
    lease = acquire_lease(d, "T-904")
    called = []
    try:
        coord.apply_result(d, "T-904", lease["lease_id"], "never-claimed.txt", "c1", "s1",
                           EMPTY, lambda: called.append(True), "apply-904")
        chk("apply_result raised", False)
    except coord.CoordinationError as e:
        chk("refused: no active claim", "no active claim" in str(e))
    chk("the downstream apply_fn was never called", called == [])
    conflicts = audit_ops(d, "apply_result_conflict")
    chk("conflict evidence recorded for this refusal too",
        len(conflicts) == 1 and conflicts[0]["decision"] == "deny")

# =========================================================================================
t("a stale result is refused before it is ever written — no silent merge")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-905")
    lease = acquire_lease(d, "T-905")
    claim = acquire_claim(d, "T-905", lease["lease_id"], "f.txt")
    coord.apply_result(d, "T-905", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                       lambda: Path(claim["path"]).write_text("v1"), "apply-v1")
    # a second writer re-acquires the now-released claim, but read the file BEFORE v1
    # landed — its base revision is the empty sentinel, which is now stale.
    claim2 = acquire_claim(d, "T-905", lease["lease_id"], "f.txt", key="claim-2")
    called = []
    try:
        coord.apply_result(d, "T-905", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                           lambda: (called.append(True), Path(claim2["path"])
                                    .write_text("v2-should-never-land")), "apply-v2")
        chk("apply_result raised for the stale revision", False)
    except coord.CoordinationError as e:
        chk("refused as stale, names both revisions",
            "refused as stale" in str(e) and "never merged" in str(e))
    chk("the downstream apply_fn was never called", called == [])
    chk("the file's content is untouched by the stale attempt",
        Path(claim2["path"]).read_text() == "v1")
    stales = audit_ops(d, "apply_result_stale")
    chk("staleness evidence recorded", len(stales) == 1
        and stales[0]["base_revision"] == EMPTY and stales[0]["current_revision"] == sha("v1"))
    # T-103 stale-claim-lifecycle fix: a stale refusal still means the caller held a valid
    # claim (it passed verify_dispatch_conflict_protection) -- that claim must not be left
    # dangling just because the result itself was refused.
    rec2, _ = coord._read_json(coord._claim_path(claim2["path"]))
    chk("the claim held by the stale caller ends up in terminal state 'released', not "
        "left dangling", rec2["state"] == "released")
    releases_after_stale = audit_ops(d, "claim_release")
    chk("release evidence is recorded for the stale-path release",
        len(releases_after_stale) == 2  # v1's own release, plus this one
        and releases_after_stale[-1]["client_id"] == "c1"
        and releases_after_stale[-1]["session_id"] == "s1")
    reclaimed_after_stale = acquire_claim(d, "T-905", lease["lease_id"], "f.txt",
                                          key="reclaim-after-stale")
    chk("the path can be claimed again after the stale-path release",
        reclaimed_after_stale["state"] == "granted")

t("a stale result — the release itself failing is recorded and never swallowed, "
  "the stale context is preserved")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-905b")
    lease = acquire_lease(d, "T-905b")
    claim = acquire_claim(d, "T-905b", lease["lease_id"], "f.txt")
    coord.apply_result(d, "T-905b", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                       lambda: Path(claim["path"]).write_text("v1"), "apply-v1")
    claim2 = acquire_claim(d, "T-905b", lease["lease_id"], "f.txt", key="claim-2")
    # The claim genuinely is valid and matching here — verify_dispatch_conflict_protection
    # must pass, exactly like the plain stale case, so the staleness check is what refuses
    # this call. What's under test is ONLY "what happens if the release call that follows
    # then itself fails" — which cannot happen through the claim's own real state (the
    # same fields that let verify pass are exactly what claim_release itself checks), so
    # the failure is induced directly: patch claim_release, call it, restore it. This is
    # the one deliberate exception to "never touch a private/internal name from a test" in
    # this suite, and only for the duration of this one call.
    real_claim_release = coord.claim_release

    def boom_release(*a, **kw):
        raise coord.CoordinationError("simulated release backend failure")

    coord.claim_release = boom_release
    called = []
    try:
        coord.apply_result(d, "T-905b", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                           lambda: called.append(True), "apply-v2-should-not-run")
        chk("apply_result raised", False)
    except coord.CoordinationError as e:
        chk("the stale context is preserved in the combined failure message",
            "refused as stale" in str(e))
        chk("the release failure is also named, not swallowed",
            "releasing the claim" in str(e) and "also failed" in str(e))
    finally:
        coord.claim_release = real_claim_release
    chk("apply_fn was still never called", called == [])
    chk("the file is still untouched", Path(claim["path"]).read_text() == "v1")
    release_failures = audit_ops(d, "apply_result_release_failed")
    chk("the release failure is recorded, distinct from a plain stale refusal",
        len(release_failures) == 1
        and "refused as stale" in release_failures[0]["apply_error"]
        and release_failures[0]["release_error"])
    # the claim itself was never actually released (the real claim_release never ran) --
    # confirm the record is exactly what it was: granted, held by claim2's acquisition.
    rec_after, _ = coord._read_json(coord._claim_path(claim2["path"]))
    chk("the claim record itself is untouched by the simulated release failure "
        "(still 'granted' -- nothing pretended a release that never happened)",
        rec_after["state"] == "granted")

t("a caller with no valid matching claim remains refused, and never pretends to release "
  "a claim it never held")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-905c")
    lease = acquire_lease(d, "T-905c")
    called = []
    try:
        coord.apply_result(d, "T-905c", lease["lease_id"], "never-claimed.txt", "c1", "s1",
                           EMPTY, lambda: called.append(True), "apply-905c")
        chk("apply_result raised", False)
    except coord.CoordinationError as e:
        chk("refused: no active claim", "no active claim" in str(e))
    chk("apply_fn was never called", called == [])
    chk("no release was attempted or recorded for a claim that was never held",
        audit_ops(d, "claim_release") == [])
    chk("only the conflict-refusal evidence is recorded, not a release or a stale entry",
        len(audit_ops(d, "apply_result_conflict")) == 1
        and audit_ops(d, "apply_result_stale") == [])

t("a current (fresh) result is accepted")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-906")
    lease = acquire_lease(d, "T-906")
    claim = acquire_claim(d, "T-906", lease["lease_id"], "f.txt")
    coord.apply_result(d, "T-906", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                       lambda: Path(claim["path"]).write_text("v1"), "apply-v1")
    claim2 = acquire_claim(d, "T-906", lease["lease_id"], "f.txt", key="claim-2")
    fresh_base = sha("v1")
    r = coord.apply_result(d, "T-906", lease["lease_id"], "f.txt", "c1", "s1", fresh_base,
                           lambda: Path(claim2["path"]).write_text("v2"), "apply-v2")
    chk("accepted", r["new_revision"] == sha("v2"))
    chk("the file now carries the new content", Path(claim2["path"]).read_text() == "v2")

# =========================================================================================
t("successful claim release is recorded")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-907")
    lease = acquire_lease(d, "T-907")
    claim = acquire_claim(d, "T-907", lease["lease_id"], "f.txt")
    coord.apply_result(d, "T-907", lease["lease_id"], "f.txt", "c1", "s1", EMPTY,
                       lambda: Path(claim["path"]).write_text("v1"), "apply-v1")
    releases = audit_ops(d, "claim_release")
    applied = audit_ops(d, "apply_result")
    chk("exactly one claim_release event recorded", len(releases) == 1
        and releases[0]["client_id"] == "c1" and releases[0]["session_id"] == "s1")
    chk("exactly one apply_result 'applied' event recorded",
        len(applied) == 1 and applied[0]["decision"] == "applied")
    rec, _ = coord._read_json(coord._claim_path(claim["path"]))
    chk("the claim record itself shows state=released", rec["state"] == "released")
    # release is a live enforcement effect, not just an audit line: the path is claimable again.
    reclaimed = acquire_claim(d, "T-907", lease["lease_id"], "f.txt", key="reclaim")
    chk("the released path can be claimed again", reclaimed["state"] == "granted")

t("failed execution still releases the claim, and the failure is never swallowed")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-908")
    lease = acquire_lease(d, "T-908")
    claim = acquire_claim(d, "T-908", lease["lease_id"], "f.txt")

    def boom():
        raise RuntimeError("apply_fn exploded")

    try:
        coord.apply_result(d, "T-908", lease["lease_id"], "f.txt", "c1", "s1", EMPTY, boom,
                           "apply-boom")
        chk("apply_result propagated the failure", False)
    except RuntimeError as e:
        chk("the original exception is raised, not swallowed", "apply_fn exploded" in str(e))
    rec, _ = coord._read_json(coord._claim_path(claim["path"]))
    chk("the claim was released despite the failure", rec["state"] == "released")
    releases = audit_ops(d, "claim_release")
    failed_events = audit_ops(d, "apply_result")
    chk("the release is recorded", len(releases) == 1)
    chk("the failure decision is recorded, distinct from a successful apply",
        len(failed_events) == 1 and failed_events[0]["decision"] == "failed"
        and "apply_fn exploded" in failed_events[0]["reason"])
    reclaimed = acquire_claim(d, "T-908", lease["lease_id"], "f.txt", key="reclaim-908")
    chk("the path is claimable again after the failure-path release",
        reclaimed["state"] == "granted")

# =========================================================================================
t("`atlas coordinator apply` — the CLI surface, end to end")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    d = make_ticket_home(home, ticket_id="T-909")
    with captured() as (out, err):
        rc_l = coordinator.cmd_lease(["acquire", "T-909", "--client", "c1", "--session", "s1",
                                     "--invocation", "i1", "--ttl-seconds", "300",
                                     "--idempotency-key", "cli-lease-909"])
    lease_id = None
    for line in out.getvalue().splitlines():
        if "lease id:" in line:
            lease_id = line.split()[-1]
    chk("lease acquired via the CLI", lease_id is not None)
    with captured():
        coordinator.cmd_claim(["acquire", "T-909", "--lease-id", lease_id, "--path", "f.txt",
                              "--client", "c1", "--session", "s1",
                              "--idempotency-key", "cli-claim-909"])
    with captured() as (out2, err2):
        try:
            rc = coordinator.cmd_apply(["T-909", "--path", "f.txt", "--lease-id", lease_id,
                                       "--client", "c1", "--session", "s1",
                                       "--base-revision", EMPTY, "--content", "hello",
                                       "--idempotency-key", "cli-apply-909"])
        except SystemExit as e:
            rc = e.code
    chk("apply exits 0", rc == 0)
    chk("the file was written via the CLI path", (home / "f.txt").read_text() == "hello")
    with captured() as (out3, err3):
        try:
            coordinator.cmd_apply(["T-909", "--path", "f.txt", "--lease-id", lease_id,
                                  "--client", "c1", "--session", "s1", "--base-revision",
                                  EMPTY, "--content", "stale-write",
                                  "--idempotency-key", "cli-apply-909-stale"])
        except SystemExit as e:
            rc2 = e.code
    chk("a stale CLI apply (claim already released) is refused, not applied",
        rc2 != 0 and "no active claim" in err3.getvalue())
    chk("the file is unchanged by the refused CLI attempt",
        (home / "f.txt").read_text() == "hello")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
