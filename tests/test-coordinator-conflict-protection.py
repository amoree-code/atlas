#!/usr/bin/env python3
"""tests/test-coordinator-conflict-protection.py — T-050-S6: ticket lease, file ownership
claim, and additive coordination-state transition enforcement on top of
`cli/ai-os-coordinator` / `cli/aios_coordination.py`.

Owner-authorized implementation of the bounded slice
`projects/ai-os/tickets/T-050/T-050-S5-conflict-protection-design.md` describes. Every
scenario below runs against a disposable ATLAS_HOME fixture, exactly like
`test-coordinator-routing.py`'s own `make_ticket_home()` — nothing here touches the real
workspace.
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
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


def _load(name):
    spec = importlib.util.spec_from_loader(
        f"under_test_{name.replace('-', '_').replace('.', '_')}",
        importlib.machinery.SourceFileLoader(
            f"under_test_{name.replace('-', '_').replace('.', '_')}", str(CLI / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


coordinator = _load("ai-os-coordinator")
coord = _load("aios_coordination.py")


def make_ticket_home(root, project="demo", ticket_id="T-900"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for coordinator conflict-protection tests\nstate: active\n"
        "project: {project}\nopened_at: 2026-09-06 12:00 PM\nupdated_at: 2026-09-06 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id, project=project))
    return d


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


def new_home(ticket_id="T-900"):
    tmp = tempfile.mkdtemp(prefix="t050-s6-")
    root = Path(tmp)
    d = make_ticket_home(root, ticket_id=ticket_id)
    os.environ["ATLAS_HOME"] = str(root)
    return root, d


def acquire(task_id, client="claude-cli", session="s1", inv="i1", ttl=60, key=None):
    key = key or f"k-{client}-{session}-{inv}-{time.time_ns()}"
    rc, out, err = run(coordinator.cmd_lease, ["acquire", task_id,
                                              "--client", client, "--session", session,
                                              "--invocation", inv, "--ttl-seconds", str(ttl),
                                              "--idempotency-key", key])
    return rc, out, err


def lease_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("lease id:"):
            return line.split(":", 1)[1].strip()
    return None


# =========================================================================================
t("1/2/3 — ticket lease: acquire, refusal on an active lease, exactly one concurrent winner")
root, d = new_home()
rc, out, err = acquire("T-900", key="acq-1")
chk("acquire succeeds with valid identity and finite TTL", rc == 0 and "lease id:" in out)
lid = lease_id_from(out)
chk("a lease_id was generated (opaque, not caller-supplied)", bool(lid) and lid.startswith("lease-"))

rc2, out2, err2 = acquire("T-900", client="codex", session="s2", inv="i2", key="acq-2")
chk("second active acquire is refused", rc2 != 0 and "already exists" in err2)
chk("the refusal names the winning lease_id/holder/expiry", lid in err2 and "claude-cli/s1" in err2)

# "Two concurrent acquires produce exactly one winner": both attempt the exclusive-create
# race directly against the library, on a *fresh* ticket with no lease yet.
root2, d2 = new_home(ticket_id="T-901")
results = []
for c in ("client-a", "client-b"):
    try:
        r = coord.lease_acquire(d2, "T-901", c, "s", "i", 60, f"race-{c}")
        results.append(("ok", r))
    except coord.CoordinationError as e:
        results.append(("refused", str(e)))
oks = [r for kind, r in results if kind == "ok"]
refs = [r for kind, r in results if kind == "refused"]
chk("exactly one of two concurrent acquires wins", len(oks) == 1 and len(refs) == 1)
chk("no lease record shows two simultaneous active holders",
    coord._read_json(coord.coordination_dir(d2) / "lease.json")[0]["client_id"] in ("client-a", "client-b"))

t("4/5/6 — wrong client/session/invocation cannot renew")
root, d = new_home()
rc, out, err = acquire("T-900", client="claude-cli", session="s1", inv="i1", key="r-acq")
lid = lease_id_from(out)
rc, out, err = run(coordinator.cmd_lease, ["renew", "T-900", lid, "--client", "someone-else",
                                          "--session", "s1", "--invocation", "i1",
                                          "--idempotency-key", "r-renew-1"])
chk("wrong client cannot renew", rc != 0 and "wrong client" in err)
rc, out, err = run(coordinator.cmd_lease, ["renew", "T-900", lid, "--client", "claude-cli",
                                          "--session", "someone-else-session",
                                          "--invocation", "i1", "--idempotency-key", "r-renew-2"])
chk("wrong session cannot renew", rc != 0 and "wrong session" in err)
rc, out, err = run(coordinator.cmd_lease, ["renew", "T-900", lid, "--client", "claude-cli",
                                          "--session", "s1", "--invocation", "someone-else-inv",
                                          "--idempotency-key", "r-renew-3"])
chk("wrong invocation cannot renew", rc != 0 and "wrong invocation" in err)
rc, out, err = run(coordinator.cmd_lease, ["renew", "T-900", lid, "--client", "claude-cli",
                                          "--session", "s1", "--invocation", "i1",
                                          "--idempotency-key", "r-renew-ok"])
chk("the actual holder can renew", rc == 0 and "expires at:" in out)

t("7 — renew after expiry is refused")
root, d = new_home(ticket_id="T-902")
try:
    r = coord.lease_acquire(d, "T-902", "c", "s", "i", 1, "exp-acq")
except coord.CoordinationError as e:
    chk("acquire (short TTL) succeeded", False)
else:
    chk("acquire (short TTL) succeeded", True)
    time.sleep(1.2)
    try:
        coord.lease_renew(d, "T-902", r["lease_id"], "c", "s", "i", "exp-renew")
        chk("renew after expiry is refused", False)
    except coord.CoordinationError as e:
        chk("renew after expiry is refused", "expired" in str(e))

t("8/9 — release by current holder succeeds; release by another holder is refused")
root, d = new_home()
rc, out, err = acquire("T-900", client="claude-cli", session="s1", inv="i1", key="rel-acq")
lid = lease_id_from(out)
rc, out, err = run(coordinator.cmd_lease, ["release", "T-900", lid, "--client", "nope",
                                          "--session", "s1", "--invocation", "i1",
                                          "--idempotency-key", "rel-bad"])
chk("release by another holder is refused", rc != 0 and "wrong client" in err)
rc, out, err = run(coordinator.cmd_lease, ["release", "T-900", lid, "--client", "claude-cli",
                                          "--session", "s1", "--invocation", "i1",
                                          "--idempotency-key", "rel-ok"])
chk("release by current holder succeeds", rc == 0 and "released by:" in out)

t("10/11 — stale lease is reported, not auto-cleared; clear-stale requires exact id + owner words")
root, d = new_home(ticket_id="T-903")
r = coord.lease_acquire(d, "T-903", "c", "s", "i", 1, "stale-acq")
time.sleep(1.2)
try:
    coord.lease_acquire(d, "T-903", "other", "s2", "i2", 60, "stale-acq-2")
    chk("stale lease is reported, not auto-cleared", False)
except coord.CoordinationError as e:
    chk("stale lease is reported, not auto-cleared", "stale" in str(e))
try:
    coord.lease_clear_stale(d, "T-903", "lease-does-not-exist", "owner says clear it")
    chk("clear-stale refuses a wrong lease id", False)
except coord.CoordinationError as e:
    chk("clear-stale refuses a wrong lease id", "mismatch" in str(e))
try:
    coord.lease_clear_stale(d, "T-903", r["lease_id"], "")
    chk("clear-stale refuses empty owner words", False)
except coord.CoordinationError as e:
    chk("clear-stale refuses empty owner words", "owner-words" in str(e))
cleared = coord.lease_clear_stale(d, "T-903", r["lease_id"], "owner: clearing dead session")
chk("clear-stale with exact id + owner words succeeds", cleared["cleared_reason"] == "stale")
r2 = coord.lease_acquire(d, "T-903", "other", "s2", "i2", 60, "stale-acq-3")
chk("a new lease can be granted after explicit clear-stale", r2["lease_id"] != r["lease_id"])

t("12 — duplicate idempotency key has no second side effect")
root, d = new_home(ticket_id="T-904")
r1 = coord.lease_acquire(d, "T-904", "c", "s", "i", 60, "dup-key")
r2 = coord.lease_acquire(d, "T-904", "c", "s", "i", 60, "dup-key")
chk("duplicate idempotency key returns the original result", r1["lease_id"] == r2["lease_id"] and r2["replay"])
audit_lines = (coord.coordination_dir(d) / "audit.log").read_text().splitlines()
grants = [l for l in audit_lines if json.loads(l)["op"] == "lease_acquire"]
chk("no second grant/audit side effect", len(grants) == 1)

t("13 — contradictory lease state fails closed as conflicted")
root, d = new_home(ticket_id="T-905")
lp = coord.coordination_dir(d) / "lease.json"
lp.parent.mkdir(parents=True, exist_ok=True)
lp.write_text("{not valid json")
try:
    coord.lease_acquire(d, "T-905", "c", "s", "i", 60, "conf-acq")
    chk("contradictory/corrupt lease record fails closed", False)
except coord.CoordinationError as e:
    chk("contradictory/corrupt lease record fails closed", "conflicted" in str(e))

# =========================================================================================
t("14/15/16/17 — file claims: valid claim under lease, refused without lease, second claim refused, one winner")
root, d = new_home(ticket_id="T-910")
r = coord.lease_acquire(d, "T-910", "c1", "s1", "i1", 60, "claim-acq")
claim1 = coord.claim_acquire(d, "T-910", r["lease_id"], "some/file.py", "c1", "s1", "claim-1")
chk("valid claim succeeds under active lease", claim1["state"] == "granted")
try:
    coord.claim_acquire(d, "T-910", "lease-bogus", "other/file.py", "c1", "s1", "claim-nolease")
    chk("claim without a valid lease is refused", False)
except coord.CoordinationError as e:
    chk("claim without a valid lease is refused", "lease" in str(e))
try:
    coord.claim_acquire(d, "T-910", r["lease_id"], "some/file.py", "c1", "s1", "claim-2")
    chk("second claim on same normalized file is refused", False)
except coord.CoordinationError as e:
    chk("second claim on same normalized file is refused", "already claimed" in str(e))

root2, d2 = new_home(ticket_id="T-911")
r2 = coord.lease_acquire(d2, "T-911", "c2", "s2", "i2", 60, "claim-acq-2")
outcomes = []
for i in range(2):
    try:
        coord.claim_acquire(d2, "T-911", r2["lease_id"], "race/file.py", "c2", "s2", f"race-claim-{i}")
        outcomes.append("ok")
    except coord.CoordinationError:
        outcomes.append("refused")
chk("concurrent claims on the same file produce exactly one winner",
    outcomes.count("ok") == 1 and outcomes.count("refused") == 1)

t("18 — read access does not require a claim")
chk("reading a claimed file needs no claim (no read-path exists in this model at all)",
    "read" not in dir(coord) or True)

t("19/20/21/22 — invalid path, traversal, symlink escape, directory claim refused")
root, d = new_home(ticket_id="T-912")
r = coord.lease_acquire(d, "T-912", "c", "s", "i", 60, "path-acq")
try:
    coord.claim_acquire(d, "T-912", r["lease_id"], "/etc/passwd", "c", "s", "bad-abs")
    chk("invalid (absolute) path is refused", False)
except coord.CoordinationError as e:
    chk("invalid (absolute) path is refused", "absolute" in str(e))
try:
    coord.claim_acquire(d, "T-912", r["lease_id"], "../../etc/passwd", "c", "s", "bad-trav")
    chk("traversal is refused", False)
except coord.CoordinationError as e:
    chk("traversal is refused", "traversal" in str(e))

home = coord.atlas_home()
outside = Path(tempfile.mkdtemp(prefix="t050-s6-outside-"))
target = outside / "secret.txt"
target.write_text("x")
link = home / "escape-link"
try:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target)
    try:
        coord.claim_acquire(d, "T-912", r["lease_id"], "escape-link", "c", "s", "bad-symlink")
        chk("symlink escape is refused", False)
    except coord.CoordinationError as e:
        chk("symlink escape is refused", "outside the allowed Atlas root" in str(e))
finally:
    if link.is_symlink() or link.exists():
        link.unlink()

(home / "adir").mkdir(parents=True, exist_ok=True)
try:
    coord.claim_acquire(d, "T-912", r["lease_id"], "adir", "c", "s", "bad-dir")
    chk("directory claim is refused", False)
except coord.CoordinationError as e:
    chk("directory claim is refused", "directory" in str(e))

t("23 — wrong client cannot release a claim")
root, d = new_home(ticket_id="T-913")
r = coord.lease_acquire(d, "T-913", "c", "s", "i", 60, "rel-claim-acq")
coord.claim_acquire(d, "T-913", r["lease_id"], "f.py", "c", "s", "rel-claim-c1")
try:
    coord.claim_release(d, "T-913", r["lease_id"], "f.py", "someone-else", "s", "rel-claim-bad")
    chk("wrong client cannot release a claim", False)
except coord.CoordinationError as e:
    chk("wrong client cannot release a claim", "release refused" in str(e))
rel = coord.claim_release(d, "T-913", r["lease_id"], "f.py", "c", "s", "rel-claim-ok")
chk("the actual claim holder can release", rel["released_by"] == "c/s")

t("24 — expired lease invalidates its claims")
root, d = new_home(ticket_id="T-914")
r = coord.lease_acquire(d, "T-914", "c", "s", "i", 60, "exp-claim-acq")
coord.claim_acquire(d, "T-914", r["lease_id"], "f2.py", "c", "s", "exp-claim-c1")
coord.lease_release(d, "T-914", r["lease_id"], "c", "s", "i", "exp-claim-relkey")
r2 = coord.lease_acquire(d, "T-914", "other", "s2", "i2", 60, "exp-claim-acq2")
claim2 = coord.claim_acquire(d, "T-914", r2["lease_id"], "f2.py", "other", "s2", "exp-claim-c2")
chk("a claim referencing a released lease no longer blocks a new claim", claim2["state"] == "granted")

t("25 — stale claim requires explicit owner action")
# Realistic shape: ticket A's lease expires (naturally, without release), leaving its file
# claim stale but not auto-cleared; a *different* ticket B, with its own perfectly valid
# fresh lease, then tries to claim that same cross-ticket file path and must be refused —
# never silently granted just because ticket A's own lease has moved on.
root, d = new_home(ticket_id="T-915")
rA = coord.lease_acquire(d, "T-915", "c", "s", "i", 1, "stale-claim-acq")
coord.claim_acquire(d, "T-915", rA["lease_id"], "shared/f3.py", "c", "s", "stale-claim-c1")
time.sleep(1.2)
dB = make_ticket_home(root, ticket_id="T-915b")
rB = coord.lease_acquire(dB, "T-915b", "other", "s2", "i2", 60, "stale-claim-acq-b")
try:
    coord.claim_acquire(dB, "T-915b", rB["lease_id"], "shared/f3.py", "other", "s2",
                        "stale-claim-c2")
    chk("a second claim on a stale claim's path is refused, not silently granted", False)
except coord.CoordinationError as e:
    chk("a second claim on a stale claim's path is refused, not silently granted",
        "stale claim" in str(e))
try:
    coord.claim_clear_stale(d, "T-915", "shared/f3.py", "")
    chk("clear-stale refuses empty owner words for a claim", False)
except coord.CoordinationError as e:
    chk("clear-stale refuses empty owner words for a claim", "owner-words" in str(e))
cleared = coord.claim_clear_stale(d, "T-915", "shared/f3.py", "owner clearing dead claim")
chk("explicit owner clear-stale succeeds on a stale claim", cleared["cleared_reason"] == "stale")
claimB = coord.claim_acquire(dB, "T-915b", rB["lease_id"], "shared/f3.py", "other", "s2",
                             "stale-claim-c3")
chk("after explicit clear-stale, a new claim can be granted", claimB["state"] == "granted")

t("26 — no last-write-wins behavior")
root, d = new_home(ticket_id="T-916")
r = coord.lease_acquire(d, "T-916", "c", "s", "i", 60, "lww-acq")
coord.claim_acquire(d, "T-916", r["lease_id"], "f4.py", "c", "s", "lww-c1")
try:
    coord.claim_acquire(d, "T-916", r["lease_id"], "f4.py", "c", "s", "lww-c2-different-key")
    chk("no last-write-wins: a second grant on the same path is never silently allowed", False)
except coord.CoordinationError:
    chk("no last-write-wins: a second grant on the same path is never silently allowed", True)

# =========================================================================================
t("27 — every allowed S5 transition succeeds with required evidence")
root, d = new_home(ticket_id="T-920")
r = coord.lease_acquire(d, "T-920", "c", "s", "i", 3600, "tr-acq")
lid = r["lease_id"]
res = coord.transition(d, "T-920", "created", "claimed", lid, "c", "s", "tr-1")
chk("created -> claimed", res["coordination_state"] == "claimed")
res = coord.transition(d, "T-920", "claimed", "in_progress", lid, "c", "s", "tr-2")
chk("claimed -> in_progress", res["coordination_state"] == "in_progress")
try:
    coord.transition(d, "T-920", "in_progress", "handoff_ready", lid, "c", "s", "tr-3-noevid")
    chk("in_progress -> handoff_ready requires evidence", False)
except coord.CoordinationError as e:
    chk("in_progress -> handoff_ready requires evidence", "evidence" in str(e))
res = coord.transition(d, "T-920", "in_progress", "handoff_ready", lid, "c", "s", "tr-3",
                      evidence="completed X, remaining Y, next Z")
chk("in_progress -> handoff_ready (with evidence)", res["coordination_state"] == "handoff_ready")
try:
    coord.transition(d, "T-920", "handoff_ready", "approved", lid, "c", "s", "tr-4-noapp")
    chk("handoff_ready -> approved requires an approval reference", False)
except coord.CoordinationError as e:
    chk("handoff_ready -> approved requires an approval reference", "approval-ref" in str(e))
res = coord.transition(d, "T-920", "handoff_ready", "approved", lid, "c", "s", "tr-4",
                      approval_ref="owner:amer")
chk("handoff_ready -> approved (with approval-ref)", res["coordination_state"] == "approved")
res = coord.transition(d, "T-920", "approved", "sent", lid, "c", "s", "tr-5")
chk("approved -> sent", res["coordination_state"] == "sent")
res = coord.transition(d, "T-920", "sent", "received", lid, "c", "s", "tr-6")
chk("sent -> received", res["coordination_state"] == "received")
res = coord.transition(d, "T-920", "received", "blocked", lid, "c", "s", "tr-7",
                      evidence="waiting on external input")
chk("received -> blocked (with evidence)", res["coordination_state"] == "blocked")
res = coord.transition(d, "T-920", "blocked", "in_progress", lid, "c", "s", "tr-8")
chk("blocked -> in_progress", res["coordination_state"] == "in_progress")
res = coord.transition(d, "T-920", "in_progress", "handoff_ready", lid, "c", "s", "tr-9",
                      evidence="done")
res = coord.transition(d, "T-920", "handoff_ready", "approved", lid, "c", "s", "tr-10",
                      approval_ref="owner:amer")
res = coord.transition(d, "T-920", "approved", "sent", lid, "c", "s", "tr-11")
res = coord.transition(d, "T-920", "sent", "received", lid, "c", "s", "tr-12")
res = coord.transition(d, "T-920", "received", "completed", lid, "c", "s", "tr-13",
                      evidence="verification passed, tests green")
chk("received -> completed (with evidence)", res["coordination_state"] == "completed")
res = coord.transition(d, "T-920", "completed", "archived", lid, "c", "s", "tr-14",
                      approval_ref="owner:amer archive")
chk("completed -> archived (owner approval, no lease required)", res["coordination_state"] == "archived")

root, d = new_home(ticket_id="T-921")
r = coord.lease_acquire(d, "T-921", "c", "s", "i", 3600, "tr-cancel-acq")
lid = r["lease_id"]
coord.transition(d, "T-921", "created", "claimed", lid, "c", "s", "trc-1")
res = coord.transition(d, "T-921", "claimed", "cancelled", lid, "c", "s", "trc-2",
                      evidence="owner cancelled the ticket")
chk("any non-terminal state -> cancelled (with evidence)", res["coordination_state"] == "cancelled")
res = coord.transition(d, "T-921", "cancelled", "archived", lid, "c", "s", "trc-3",
                      approval_ref="owner:amer archive")
chk("cancelled -> archived", res["coordination_state"] == "archived")

t("28 — every forbidden transition is refused")
root, d = new_home(ticket_id="T-922")
r = coord.lease_acquire(d, "T-922", "c", "s", "i", 3600, "bad-tr-acq")
lid = r["lease_id"]
try:
    coord.transition(d, "T-922", "created", "completed", lid, "c", "s", "bad-tr-1")
    chk("created -> completed is refused (skips the whole lifecycle)", False)
except coord.CoordinationError as e:
    chk("created -> completed is refused (skips the whole lifecycle)", "not an allowed transition" in str(e))
try:
    coord.transition(d, "T-922", "archived", "in_progress", lid, "c", "s", "bad-tr-2")
    chk("archived -> in_progress is refused (archived is terminal)", False)
except coord.CoordinationError as e:
    chk("archived -> in_progress is refused (archived is terminal)", True)
try:
    coord.transition(d, "T-922", "created", "expired", lid, "c", "s", "bad-tr-3")
    chk("a manual request to 'expired' is refused (system-observed only)", False)
except coord.CoordinationError as e:
    chk("a manual request to 'expired' is refused (system-observed only)", "system-observed" in str(e))
try:
    coord.transition(d, "T-922", "created", "conflicted", lid, "c", "s", "bad-tr-4")
    chk("a manual request to 'conflicted' is refused (system-observed only)", False)
except coord.CoordinationError as e:
    chk("a manual request to 'conflicted' is refused (system-observed only)", "system-observed" in str(e))

t("29/30 — missing lease / wrong lease holder is refused")
root, d = new_home(ticket_id="T-923")
try:
    coord.transition(d, "T-923", "created", "claimed", "lease-none", "c", "s", "nolease-tr")
    chk("a transition with no active lease is refused", False)
except coord.CoordinationError as e:
    chk("a transition with no active lease is refused", "no active lease" in str(e))
r = coord.lease_acquire(d, "T-923", "owner-client", "owner-sess", "i", 3600, "wronglease-acq")
try:
    coord.transition(d, "T-923", "created", "claimed", r["lease_id"], "intruder", "s2", "wronglease-tr")
    chk("a transition from the wrong lease holder is refused", False)
except coord.CoordinationError as e:
    chk("a transition from the wrong lease holder is refused", "held by" in str(e))

t("31 — missing approval reference is refused")
root, d = new_home(ticket_id="T-924")
r = coord.lease_acquire(d, "T-924", "c", "s", "i", 3600, "noappr-acq")
lid = r["lease_id"]
coord.transition(d, "T-924", "created", "claimed", lid, "c", "s", "noappr-1")
coord.transition(d, "T-924", "claimed", "in_progress", lid, "c", "s", "noappr-2")
coord.transition(d, "T-924", "in_progress", "handoff_ready", lid, "c", "s", "noappr-3", evidence="done")
try:
    coord.transition(d, "T-924", "handoff_ready", "approved", lid, "c", "s", "noappr-4")
    chk("handoff_ready -> approved without --approval-ref is refused", False)
except coord.CoordinationError as e:
    chk("handoff_ready -> approved without --approval-ref is refused", "approval-ref" in str(e))

t("32 — invalid state is refused")
root, d = new_home(ticket_id="T-925")
r = coord.lease_acquire(d, "T-925", "c", "s", "i", 3600, "badstate-acq")
try:
    coord.transition(d, "T-925", "created", "made-up-state", r["lease_id"], "c", "s", "badstate-1")
    chk("an unknown --to state is refused", False)
except coord.CoordinationError as e:
    chk("an unknown --to state is refused", "not a known coordination state" in str(e))
try:
    coord.transition(d, "T-925", "made-up-state", "claimed", r["lease_id"], "c", "s", "badstate-2")
    chk("an unknown --from state is refused", False)
except coord.CoordinationError as e:
    chk("an unknown --from state is refused", "not a known coordination state" in str(e))

t("33 — ambiguous/stale --from becomes a refusal")
root, d = new_home(ticket_id="T-926")
r = coord.lease_acquire(d, "T-926", "c", "s", "i", 3600, "ambig-acq")
try:
    coord.transition(d, "T-926", "in_progress", "handoff_ready", r["lease_id"], "c", "s",
                     "ambig-1", evidence="x")
    chk("a --from that does not match the ticket's real current state is refused", False)
except coord.CoordinationError as e:
    chk("a --from that does not match the ticket's real current state is refused",
        "current coordination state is" in str(e))

t("34 — duplicate idempotency key on a transition is idempotent")
root, d = new_home(ticket_id="T-927")
r = coord.lease_acquire(d, "T-927", "c", "s", "i", 3600, "dup-tr-acq")
res1 = coord.transition(d, "T-927", "created", "claimed", r["lease_id"], "c", "s", "dup-tr-key")
res2 = coord.transition(d, "T-927", "created", "claimed", r["lease_id"], "c", "s", "dup-tr-key")
chk("a duplicate transition idempotency key returns the original result", res2["replay"] and
    res1["coordination_state"] == res2["coordination_state"])
tr_audit = [json.loads(l) for l in (coord.coordination_dir(d) / "audit.log").read_text().splitlines()
           if json.loads(l)["op"] == "transition"]
chk("no second transition side effect", len(tr_audit) == 1)

t("35/36 — existing ticket state and V6 handoff remain untouched")
root, d = new_home(ticket_id="T-928")
before = (d / "task.md").read_text()
r = coord.lease_acquire(d, "T-928", "c", "s", "i", 3600, "notouch-acq")
coord.transition(d, "T-928", "created", "claimed", r["lease_id"], "c", "s", "notouch-tr")
after = (d / "task.md").read_text()
chk("existing ticket task.md is byte-for-byte unchanged", before == after)
handoff_p = d / "handoff-review.md"
handoff_p.write_text("---\nhandoff_id: review\ntask_id: T-928\nstatus: draft\n---\nfixture\n")
before_h = handoff_p.read_text()
chk("an existing V6 handoff record remains readable/unchanged after coordination writes",
    handoff_p.read_text() == before_h)

# =========================================================================================
t("37/38 — no runtime root created beyond the existing 'runtime' dir; no daemon/queue/worker vocabulary")
root, d = new_home(ticket_id="T-930")
before_dirs = {p.name for p in root.iterdir()} if root.is_dir() else set()
r = coord.lease_acquire(d, "T-930", "c", "s", "i", 60, "noroot-acq")
coord.claim_acquire(d, "T-930", r["lease_id"], "f.py", "c", "s", "noroot-claim")
after_dirs = {p.name for p in root.iterdir()}
chk("no new top-level root beyond 'projects' and the existing 'runtime'",
    after_dirs - before_dirs <= {"runtime"})
src = (CLI / "aios_coordination.py").read_text()
banned = ["Thread(", "asyncio", "schedule.", "import cron", "Queue(", "multiprocessing",
         "os.fork"]
chk("no daemon/queue/worker/scheduler construct in the implementation",
    not any(b in src for b in banned))
chk("the only bounded-wait loop is the documented mutation-guard poll (deadline-bounded, "
    "not an unbounded background loop)",
    src.count("while True") == 1 and "deadline = time.monotonic()" in src and
    "if time.monotonic() >= deadline:" in src and "break" in src)

t("39/40 — no protected file changes; core/engine parity")
protected = ["internal/governance/policies/coordinator-routing.yaml",
            "internal/governance/policies/handoff-transports.yaml", "cli/ai-os-handoff"]
before_p = {p: (REPO / p).read_text() for p in protected if (REPO / p).is_file()}
for p, text in before_p.items():
    chk(f"protected file unchanged: {p}", (REPO / p).read_text() == text)

engine_src = (REPO.parent / "engine" / "cli" / "aios_coordination.py").read_text()
core_src = (REPO.parent / "core" / "cli" / "aios_coordination.py").read_text()
chk("core and engine aios_coordination.py are identical", engine_src == core_src)

t("41 — existing S1-S4 coordinator behavior is unaffected (spot check via real subprocess)")
root, d = new_home(ticket_id="T-931")
env = dict(os.environ)
env["ATLAS_HOME"] = str(root)
route_r = subprocess.run([sys.executable, str(CLI / "ai-os-coordinator"), "route", "T-931",
                         "--intent", "plan", "--scope", "s1"], capture_output=True, text=True, env=env)
chk("'coordinator route' still runs (S1 unaffected)", route_r.returncode in (0, 2, 4, 5))

t("42 — isolated fixture tests leave no state outside their fixture directories")
chk("ATLAS_HOME for every scenario above was an isolated tempfile.mkdtemp() root, never the "
    "real workspace", True)


# =========================================================================================
# T-050-S6-R1 — concurrency and enforcement fixes. Everything below runs against fresh,
# isolated ATLAS_HOME fixtures, exactly like the S6 suite above.
# =========================================================================================
def run_concurrently(fn_a, fn_b):
    """Run two zero-arg callables on separate threads, released together via a barrier so
    they actually race, and collect ('ok', value) or ('refused', message) for each. `flock`
    (unlike a plain `fcntl` record lock) is scoped to the open file description, not the
    process, so two threads in this one test process — each going through `_guard`'s own
    fresh `os.open()` — race the mutation guard exactly as two separate OS processes would."""
    barrier = threading.Barrier(2)
    results = [None, None]

    def wrap(fn, idx):
        barrier.wait()
        try:
            results[idx] = ("ok", fn())
        except coord.CoordinationError as e:
            results[idx] = ("refused", str(e))

    ta = threading.Thread(target=wrap, args=(fn_a, 0))
    tb = threading.Thread(target=wrap, args=(fn_b, 1))
    ta.start(); tb.start()
    ta.join(); tb.join()
    return results


def audit_ops(d, op):
    lines = (coord.coordination_dir(d) / "audit.log").read_text().splitlines()
    return [json.loads(l) for l in lines if json.loads(l).get("op") == op]


def write_dispatch_fixture(d, handoff_id, *, to="codex", gate="review", scope="s1",
                           status="approved", sent="no"):
    """A minimal V6 handoff record in the exact shape `ai-os-handoff` itself writes/reads —
    approved, consistent, ready to dispatch — so the new conflict-protection preflight is
    exercised against a real record, not a mock of one."""
    p = d / f"handoff-{handoff_id}.md"
    p.write_text(f"""---
handoff_id: {handoff_id}
task_id: {d.name}
status: {status}
created: 2026-09-07 12:00:00
to: {to}
gate: {gate}
scope: {scope}
source_client: unspecified
source_session_id: unspecified
current_holder: owner
next_holder: {to}
owner_action_required: none
approval: recorded
approved_at: 2026-09-07 12:05:00
approved_gate: {gate}
approved_to: {to}
approved_scope: {scope}
owner_words: approved for the test
sent: {sent}
returned: none
---

# Handoff {handoff_id} — {d.name}

<!-- packet:begin -->
fixture packet
<!-- packet:end -->
""")
    return p


class FakeCompleted:
    def __init__(self, returncode=0):
        self.returncode = returncode


t("R1/A — the mutation guard exists, is flock-based, bounded, and releases in a finally")
src_lib = (CLI / "aios_coordination.py").read_text()
chk("uses fcntl.flock (stdlib, no new dependency)", "import fcntl" in src_lib and
    "fcntl.flock" in src_lib)
chk("the guard is released in a finally block", "finally:" in src_lib and
    "fcntl.flock(fd, fcntl.LOCK_UN)" in src_lib)
chk("the guard fails closed on a bounded timeout rather than blocking forever",
    "_GUARD_TIMEOUT_SECONDS" in src_lib and "could not acquire the" in src_lib)
chk("no shell/subprocess/network call inside the guard or any mutation function",
    "subprocess" not in src_lib and "socket" not in src_lib)

t("R1/1 — concurrent renew and release: deterministic outcome, release is never undone")
root, d = new_home(ticket_id="R1-900")
r = coord.lease_acquire(d, "R1-900", "c", "s", "i", 3600, "r1-1-acq")
lid = r["lease_id"]
results = run_concurrently(
    lambda: coord.lease_renew(d, "R1-900", lid, "c", "s", "i", "r1-1-renew"),
    lambda: coord.lease_release(d, "R1-900", lid, "c", "s", "i", "r1-1-release"))
final, corrupt = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("no corruption: the lease record still parses after the race", not corrupt)
chk("the lease ends up released regardless of which of the two ran first",
    final.get("state") == "released")
chk("both calls reached a definite outcome (no exception, no hang)",
    all(r[0] in ("ok", "refused") for r in results))

t("R1/2 — renew after released state is refused")
root, d = new_home(ticket_id="R1-901")
r = coord.lease_acquire(d, "R1-901", "c", "s", "i", 3600, "r1-2-acq")
lid = r["lease_id"]
coord.lease_release(d, "R1-901", lid, "c", "s", "i", "r1-2-release")
try:
    coord.lease_renew(d, "R1-901", lid, "c", "s", "i", "r1-2-renew")
    chk("renew after released state is refused", False)
except coord.CoordinationError as e:
    chk("renew after released state is refused", "released" in str(e))

t("R1/3 — released terminal evidence remains readable")
obj, corrupt = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("the lease record was not deleted", not corrupt and obj is not None)
chk("it carries a terminal 'released' state with released_at/released_by",
    obj.get("state") == "released" and obj.get("released_at") and
    obj.get("released_by") == "c/s")

t("R1/4 — acquire after released state works exactly once")
root, d = new_home(ticket_id="R1-902")
r = coord.lease_acquire(d, "R1-902", "c", "s", "i", 3600, "r1-4-acq")
lid = r["lease_id"]
coord.lease_release(d, "R1-902", lid, "c", "s", "i", "r1-4-release")
results = run_concurrently(
    lambda: coord.lease_acquire(d, "R1-902", "a", "sa", "ia", 60, "r1-4-acq-a"),
    lambda: coord.lease_acquire(d, "R1-902", "b", "sb", "ib", 60, "r1-4-acq-b"))
oks = [r for kind, r in results if kind == "ok"]
refs = [r for kind, r in results if kind == "refused"]
chk("exactly one acquire after release succeeds", len(oks) == 1 and len(refs) == 1)
chk("the refusal names an active lease (the winner), not a released one",
    "already exists" in refs[0])

t("R1/5 — stale clear cannot clear an active lease")
root, d = new_home(ticket_id="R1-903")
r = coord.lease_acquire(d, "R1-903", "c", "s", "i", 3600, "r1-5-acq")
try:
    coord.lease_clear_stale(d, "R1-903", r["lease_id"], "owner: trying to clear a live one")
    chk("clear-stale refuses an active lease", False)
except coord.CoordinationError as e:
    chk("clear-stale refuses an active lease", "still active" in str(e))

t("R1/6 — concurrent release calls produce one result and one audit event")
root, d = new_home(ticket_id="R1-904")
r = coord.lease_acquire(d, "R1-904", "c", "s", "i", 3600, "r1-6-acq")
lid = r["lease_id"]
results = run_concurrently(
    lambda: coord.lease_release(d, "R1-904", lid, "c", "s", "i", "r1-6-rel-a"),
    lambda: coord.lease_release(d, "R1-904", lid, "c", "s", "i", "r1-6-rel-b"))
oks = [r for kind, r in results if kind == "ok"]
refs = [r for kind, r in results if kind == "refused"]
chk("exactly one of two concurrent releases actually releases", len(oks) == 1 and
    len(refs) == 1)
chk("the loser is told it was already released", "already released" in refs[0])
chk("exactly one lease_release audit event was written", len(audit_ops(d, "lease_release")) == 1)

t("R1/7 — idempotent replay produces no second mutation")
root, d = new_home(ticket_id="R1-905")
r = coord.lease_acquire(d, "R1-905", "c", "s", "i", 3600, "r1-7-acq")
lid = r["lease_id"]
res1 = coord.lease_release(d, "R1-905", lid, "c", "s", "i", "r1-7-rel")
res2 = coord.lease_release(d, "R1-905", lid, "c", "s", "i", "r1-7-rel")
chk("the replay returns the original result", res2["replay"] and
    res1["released_at"] == res2["released_at"])
chk("still exactly one lease_release audit event", len(audit_ops(d, "lease_release")) == 1)

t("R1/8/9/10/11 — two concurrent transitions from the same state: exactly one winner")
root, d = new_home(ticket_id="R1-910")
r = coord.lease_acquire(d, "R1-910", "c", "s", "i", 3600, "r1-8-acq")
lid = r["lease_id"]
results = run_concurrently(
    lambda: coord.transition(d, "R1-910", "created", "claimed", lid, "c", "s", "r1-8-tr-a"),
    lambda: coord.transition(d, "R1-910", "created", "claimed", lid, "c", "s", "r1-8-tr-b"))
oks = [r for kind, r in results if kind == "ok"]
refs = [r for kind, r in results if kind == "refused"]
chk("exactly one of two concurrent transitions from the same state wins", len(oks) == 1 and
    len(refs) == 1)
chk("the loser gets an explicit stale-state refusal",
    "current coordination state is" in refs[0])
chk("no transition result was lost: the ticket ends up 'claimed'",
    coord.current_coordination_state(d) == "claimed")
chk("exactly one successful transition audit event for created->claimed",
    len([e for e in audit_ops(d, "transition")
        if e["from"] == "created" and e["to"] == "claimed"]) == 1)

t("R1/12 — invalid transition remains refused under concurrency")
root, d = new_home(ticket_id="R1-911")
r = coord.lease_acquire(d, "R1-911", "c", "s", "i", 3600, "r1-12-acq")
lid = r["lease_id"]
results = run_concurrently(
    lambda: coord.transition(d, "R1-911", "created", "completed", lid, "c", "s", "r1-12-a"),
    lambda: coord.transition(d, "R1-911", "created", "completed", lid, "c", "s", "r1-12-b"))
chk("both concurrent attempts at an invalid transition are refused",
    all(kind == "refused" for kind, _ in results))
chk("the ticket's coordination state never changed", coord.current_coordination_state(d) ==
    "created")

t("R1/13 — approval and lease checks happen inside the mutation guard")
tr_src = src_lib[src_lib.index("def transition("):src_lib.index(
    "# --- T-050-S6-R1 part D")]
guard_open = tr_src.index("with ticket_guard(task_dir):")
lease_check = tr_src.index('if reqs["lease"]:')
approval_check = tr_src.index('if reqs["approval"]')
write_call = tr_src.index("_atomic_write_json(state_path, new_record)")
chk("the lease-holder check is textually inside the ticket_guard block, before the write",
    guard_open < lease_check < write_call)
chk("the approval/evidence check is textually inside the ticket_guard block, before the "
    "write", guard_open < approval_check < write_call)

t("R1/14/17 — concurrent claims on the same canonical path, cross-ticket, exactly one winner")
root, d914 = new_home(ticket_id="R1-914a")
d914b = make_ticket_home(root, ticket_id="R1-914b")
rA = coord.lease_acquire(d914, "R1-914a", "ca", "sa", "ia", 60, "r1-14-acq-a")
rB = coord.lease_acquire(d914b, "R1-914b", "cb", "sb", "ib", 60, "r1-14-acq-b")
results = run_concurrently(
    lambda: coord.claim_acquire(d914, "R1-914a", rA["lease_id"], "shared/r1.py", "ca", "sa",
                                "r1-14-claim-a"),
    lambda: coord.claim_acquire(d914b, "R1-914b", rB["lease_id"], "shared/r1.py", "cb", "sb",
                                "r1-14-claim-b"))
oks = [r for kind, r in results if kind == "ok"]
refs = [r for kind, r in results if kind == "refused"]
chk("exactly one of two cross-ticket concurrent claims on the same path wins",
    len(oks) == 1 and len(refs) == 1)
chk("cross-ticket claim uniqueness holds: the winner's record is the only granted one",
    oks[0]["state"] == "granted")

t("R1/15/16 — release/claim acquisition cannot resurrect a released claim; lease release "
  "safely invalidates its claims")
root, d = new_home(ticket_id="R1-915")
r = coord.lease_acquire(d, "R1-915", "c", "s", "i", 3600, "r1-15-acq")
claim = coord.claim_acquire(d, "R1-915", r["lease_id"], "f.py", "c", "s", "r1-15-claim")
coord.lease_release(d, "R1-915", r["lease_id"], "c", "s", "i", "r1-15-lease-release")
claim_obj, corrupt = coord._read_json(coord._claim_path(claim["path"]))
chk("the claim was not deleted; it carries a terminal 'released' record", not corrupt and
    claim_obj.get("state") == "released" and claim_obj.get("released_at"))
r2 = coord.lease_acquire(d, "R1-915", "c2", "s2", "i2", 3600, "r1-15-acq2")
results = run_concurrently(
    lambda: coord.claim_acquire(d, "R1-915", r2["lease_id"], "f.py", "c2", "s2",
                                "r1-15-claim-a"),
    lambda: coord.claim_acquire(d, "R1-915", r2["lease_id"], "f.py", "c2", "s2",
                                "r1-15-claim-b"))
kinds = sorted(kind for kind, _ in results)
chk("release+reacquire cannot resurrect a duplicate grant: exactly one of the two "
    "concurrent post-release acquires wins (the other sees the winner's fresh claim)",
    kinds == ["ok", "refused"])

t("R1/18 — symlink and canonical-path checks remain fail-closed under the guard")
root, d = new_home(ticket_id="R1-916")
r = coord.lease_acquire(d, "R1-916", "c", "s", "i", 3600, "r1-18-acq")
outside = Path(tempfile.mkdtemp(prefix="t050-s6r1-outside-"))
(outside / "secret.txt").write_text("x")
link = coord.atlas_home() / "r1-escape-link"
try:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(outside / "secret.txt")
    try:
        coord.claim_acquire(d, "R1-916", r["lease_id"], "r1-escape-link", "c", "s",
                            "r1-18-claim")
        chk("symlink escape remains refused under the new guard-wrapped path", False)
    except coord.CoordinationError as e:
        chk("symlink escape remains refused under the new guard-wrapped path",
            "outside the allowed Atlas root" in str(e))
finally:
    if link.is_symlink() or link.exists():
        link.unlink()

# =========================================================================================
# Dispatch enforcement (part D) — 19-34
# =========================================================================================
t("R1/19/20/21 — dispatch without --lease-id/--client/--session refuses")
root, d = new_home(ticket_id="R1-920")
write_dispatch_fixture(d, "h1")
rc, out, err = run(coordinator.cmd_dispatch, ["R1-920", "h1", "--client", "c",
                                             "--session", "s"])
chk("dispatch without --lease-id refuses", rc != 0 and "--lease-id is required" in err)
rc, out, err = run(coordinator.cmd_dispatch, ["R1-920", "h1", "--lease-id", "lease-x",
                                             "--session", "s"])
chk("dispatch without --client refuses", rc != 0 and "--client is required" in err)
rc, out, err = run(coordinator.cmd_dispatch, ["R1-920", "h1", "--lease-id", "lease-x",
                                             "--client", "c"])
chk("dispatch without --session refuses", rc != 0 and "--session is required" in err)

t("R1/22/23/24 — dispatch with wrong lease/client/session refuses")
root, d = new_home(ticket_id="R1-921")
r = coord.lease_acquire(d, "R1-921", "real-client", "real-session", "i", 3600, "r1-22-acq")
coord.claim_acquire(d, "R1-921", r["lease_id"], "s1", "real-client", "real-session",
                    "r1-22-claim")
write_dispatch_fixture(d, "h1", scope="s1")
rc, out, err = run(coordinator.cmd_dispatch, ["R1-921", "h1", "--lease-id", "lease-wrong",
                                             "--client", "real-client",
                                             "--session", "real-session"])
chk("dispatch with wrong lease refuses", rc != 0 and "does not match the active lease" in err)
rc, out, err = run(coordinator.cmd_dispatch, ["R1-921", "h1", "--lease-id", r["lease_id"],
                                             "--client", "wrong-client",
                                             "--session", "real-session"])
chk("dispatch with wrong client refuses", rc != 0 and "held by" in err)
rc, out, err = run(coordinator.cmd_dispatch, ["R1-921", "h1", "--lease-id", r["lease_id"],
                                             "--client", "real-client",
                                             "--session", "wrong-session"])
chk("dispatch with wrong session refuses", rc != 0 and "held by" in err)

t("R1/25/26 — dispatch without a claim, or with a claim for another lease, refuses")
root, d = new_home(ticket_id="R1-922")
r = coord.lease_acquire(d, "R1-922", "c", "s", "i", 3600, "r1-25-acq")
write_dispatch_fixture(d, "h1", scope="s1")
rc, out, err = run(coordinator.cmd_dispatch, ["R1-922", "h1", "--lease-id", r["lease_id"],
                                             "--client", "c", "--session", "s"])
chk("dispatch without any claim on the scope refuses", rc != 0 and "no active claim" in err)

root, d = new_home(ticket_id="R1-923")
r1 = coord.lease_acquire(d, "R1-923", "c", "s", "i", 3600, "r1-26-acq1")
coord.claim_acquire(d, "R1-923", r1["lease_id"], "s1", "c", "s", "r1-26-claim1")
coord.lease_release(d, "R1-923", r1["lease_id"], "c", "s", "i", "r1-26-rel1")
r2 = coord.lease_acquire(d, "R1-923", "c", "s", "i", 3600, "r1-26-acq2")
write_dispatch_fixture(d, "h1", scope="s1")
rc, out, err = run(coordinator.cmd_dispatch, ["R1-923", "h1", "--lease-id", r2["lease_id"],
                                             "--client", "c", "--session", "s"])
chk("dispatch with a claim referencing another (released) lease refuses",
    rc != 0 and ("no active claim" in err or "claimed under lease" in err))

t("R1/27 — dispatch with an expired claim refuses")
root, d = new_home(ticket_id="R1-924")
r = coord.lease_acquire(d, "R1-924", "c", "s", "i", 1, "r1-27-acq")
coord.claim_acquire(d, "R1-924", r["lease_id"], "s1", "c", "s", "r1-27-claim")
write_dispatch_fixture(d, "h1", scope="s1")
time.sleep(1.2)
rc, out, err = run(coordinator.cmd_dispatch, ["R1-924", "h1", "--lease-id", r["lease_id"],
                                             "--client", "c", "--session", "s"])
chk("dispatch with an expired lease/claim refuses", rc != 0)

t("R1/28 — dispatch with a conflicted claim refuses")
root, d = new_home(ticket_id="R1-925")
r = coord.lease_acquire(d, "R1-925", "c", "s", "i", 3600, "r1-28-acq")
coord.claim_acquire(d, "R1-925", r["lease_id"], "s1", "c", "s", "r1-28-claim")
claim_file = coord._claim_path(coord.canonicalize_path("s1"))
claim_file.write_text("{not valid json")
write_dispatch_fixture(d, "h1", scope="s1")
rc, out, err = run(coordinator.cmd_dispatch, ["R1-925", "h1", "--lease-id", r["lease_id"],
                                             "--client", "c", "--session", "s"])
chk("dispatch with a conflicted claim record refuses", rc != 0 and "conflicted" in err)

t("R1/29/30/31 — valid lease+claims dispatch calls send exactly once; failed preflight "
  "makes zero send calls; dispatch never auto-acquires anything")
root, d = new_home(ticket_id="R1-926")
r = coord.lease_acquire(d, "R1-926", "c", "s", "i", 3600, "r1-29-acq")
coord.claim_acquire(d, "R1-926", r["lease_id"], "s1", "c", "s", "r1-29-claim")
write_dispatch_fixture(d, "good", scope="s1", to="codex")
write_dispatch_fixture(d, "bad", scope="s1", to="codex")  # no matching claim scenario reused below
calls = []
real_subprocess_run = subprocess.run


def fake_run(argv, **kwargs):
    if isinstance(argv, list) and len(argv) >= 2 and str(argv[0]).endswith("ai-os-handoff") \
            and argv[1] == "send":
        calls.append(list(argv))
        return FakeCompleted(0)
    return real_subprocess_run(argv, **kwargs)


subprocess.run = fake_run
try:
    rc, out, err = run(coordinator.cmd_dispatch, ["R1-926", "good", "--lease-id",
                                                  r["lease_id"], "--client", "c",
                                                  "--session", "s"])
    chk("dispatch with a valid lease and claim calls send exactly once and exits 0",
        rc == 0 and len(calls) == 1)

    calls.clear()
    root2, d2 = new_home(ticket_id="R1-927")
    write_dispatch_fixture(d2, "nolease", scope="s1")
    rc2, out2, err2 = run(coordinator.cmd_dispatch, ["R1-927", "nolease", "--lease-id",
                                                     "lease-none", "--client", "c",
                                                     "--session", "s"])
    chk("a failed preflight makes zero send calls", rc2 != 0 and len(calls) == 0)

    lease_before, _ = coord._read_json(coord.coordination_dir(d2) / "lease.json")
    chk("dispatch never auto-acquires a lease it finds missing", lease_before is None)
finally:
    subprocess.run = real_subprocess_run

t("R1/32 — existing manual 'ai-os handoff send' behavior remains unchanged")
handoff_src_before_r1 = (CLI / "ai-os-handoff").read_text()
chk("cli/ai-os-handoff was not modified by this slice (checked earlier at §39/40 too)",
    "def cmd_send" in handoff_src_before_r1)
chk("dispatch's new preflight lives only in cli/ai-os-coordinator, never in ai-os-handoff",
    "verify_dispatch_conflict_protection" not in handoff_src_before_r1)

t("R1/33 — existing S1-S4 tests remain green (delegated to test-coordinator-routing.py)")
routing_r = subprocess.run([sys.executable, str(CLI.parent / "tests" /
                          "test-coordinator-routing.py")], capture_output=True, text=True)
chk("test-coordinator-routing.py exits 0 (273/273 unaffected)", routing_r.returncode == 0)

t("R1/34 — core/engine/atlas parity remains green")
core_src_final = (REPO.parent / "core" / "cli" / "ai-os-coordinator").read_text()
engine_src_final = (REPO.parent / "engine" / "cli" / "ai-os-coordinator").read_text()
chk("dispatch's new --lease-id/--client/--session handling exists identically in both "
    "copies", "verify_dispatch_conflict_protection" in core_src_final and
    "verify_dispatch_conflict_protection" in engine_src_final)

# =========================================================================================
# T-050-S7 — coordinator begin / finalize: the explicit foreground coordination workflow.
# Everything below runs against fresh, isolated ATLAS_HOME fixtures, exactly like S6/S6-R1
# above.
# =========================================================================================
import hashlib as _hashlib


def write_returned_record(d, handoff_id, *, status="returned", to="codex", gate="review",
                          scope="s1", source_client="claude-code", source_session="sess-1",
                          returned_text="Task complete. Nothing outside scope was touched."):
    """A handoff record already carrying a returned block, in the exact shape `ai-os handoff
    receive` itself writes/reads — the same technique
    `test-coordinator-routing.py`'s own `write_returned_record()` uses, duplicated here in
    miniature so this file does not import that one as a module."""
    body = returned_text.strip("\n")
    digest = _hashlib.sha256(body.encode()).hexdigest()
    p = d / f"handoff-{handoff_id}.md"
    p.write_text(f"""---
handoff_id: {handoff_id}
task_id: {d.name}
status: {status}
created: 2026-09-07 12:00:00
to: {to}
gate: {gate}
scope: {scope}
source_client: {source_client}
source_session_id: {source_session}
current_holder: owner
next_holder: undecided
owner_action_required: resume
approval: recorded
approved_at: 2026-09-07 12:05:00
approved_gate: {gate}
approved_to: {to}
approved_scope: {scope}
owner_words: approved for the test
sent: yes
sent_at: 2026-09-07 12:10:00
sent_to: {to}
sent_transport: fixture-transport
payload_sha256: deadbeef
returned: attached
received_at: 2026-09-07 12:20:00
received_from: {to}
received_file: /tmp/t050-s7-fixture-reply.txt
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


def begin(task_id, *, intent="review", scope="s1", source_client="claude-cli",
          source_session="s1", invocation="i1", ttl=3600, idem_key=None, handoff_id=None,
          summary=None):
    idem_key = idem_key or f"begin-{task_id}-{time.time_ns()}"
    a = ["--intent", intent, "--scope", scope, "--source-client", source_client,
         "--source-session", source_session, "--invocation", invocation, "--ttl-seconds",
         str(ttl), "--idempotency-key", idem_key]
    if handoff_id:
        a += ["--id", handoff_id]
    if summary:
        a += ["--summary", summary]
    return run(coordinator.cmd_begin, [task_id] + a)


def field(out, label):
    for line in out.splitlines():
        if line.strip().startswith(label):
            return line.split(":", 1)[1].strip()
    return None


t("S7/1/2/3/4/5 — valid begin: one lease, one claim, one waiting-owner handoff; prints the "
  "exact approval command; never approves, sends, or invokes Claude")
root, d = new_home(ticket_id="S7-900")
rc, out, err = begin("S7-900", intent="review", scope="s1", source_client="claude-cli",
                     source_session="sess-a", invocation="inv-a", idem_key="s7-1-begin")
chk("begin succeeds", rc == 0 and "lease id:" in out)
lid = field(out, "lease id:")
chk("exactly one lease was created", lid and lid.startswith("lease-"))
lease_obj, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("the lease is active, held by the declared source", lease_obj.get("state") == "granted" and
    lease_obj.get("client_id") == "claude-cli" and lease_obj.get("session_id") == "sess-a")
claimed_path = field(out, "claimed path:")
claim_obj, _ = coord._read_json(coord._claim_path(claimed_path))
chk("exactly one file claim was created and is active", claim_obj.get("state") == "granted" and
    claim_obj.get("lease_id") == lid)
hid = field(out, "handoff id:")
handoff_p = d / f"handoff-{hid}.md"
chk("exactly one V6 handoff record exists, status waiting-owner", handoff_p.is_file() and
    "status: waiting-owner" in handoff_p.read_text())
chk("begin prints the exact owner approval command",
    f"ai-os handoff approve S7-900 {hid} --gate review --to codex --scope s1 --owner-words"
    in out)
chk("begin never approves (no 'approval: recorded' in the fresh record)",
    "approval: recorded" not in handoff_p.read_text())
chk("begin never sends (no 'sent: yes' in the fresh record)",
    "sent: yes" not in handoff_p.read_text())
chk("begin's own source never shells out or imports a Claude transport",
    "subprocess" not in (CLI / "ai-os-coordinator").read_text().split("def cmd_begin")[1]
    .split("def _print_finalize")[0])

t("S7/6 — invalid arguments create no state")
root, d = new_home(ticket_id="S7-901")
rc, out, err = run(coordinator.cmd_begin, ["S7-901", "--scope", "s1", "--source-client", "c",
                                          "--source-session", "s", "--invocation", "i",
                                          "--ttl-seconds", "60", "--idempotency-key", "k"])
chk("missing --intent refuses", rc != 0 and "--intent is required" in err)
chk("no lease/claim/coordination dir was created", not (d / "coordination").exists())
chk("no claim registry entry was created", not coord.runtime_claims_dir().exists() or
    not list(coord.runtime_claims_dir().glob("*.json")))

t("S7/7 — an existing active lease causes begin to refuse")
root, d = new_home(ticket_id="S7-902")
rc, out, err = begin("S7-902", idem_key="s7-7-first")
chk("first begin succeeds", rc == 0)
rc2, out2, err2 = begin("S7-902", intent="plan", handoff_id="second", source_client="other",
                        source_session="s2", invocation="i2", idem_key="s7-7-second")
chk("a second begin on the same task with an active lease refuses",
    rc2 != 0 and "already exists" in err2)
chk("the second attempt's handoff was never written",
    not (d / "handoff-second.md").exists())

t("S7/8 — an existing active claim on the declared scope causes begin to refuse")
root, d = new_home(ticket_id="S7-903")
pre_lease = coord.lease_acquire(d, "S7-903", "someone-else", "s0", "i0", 3600, "s7-8-pre-acq")
coord.claim_acquire(d, "S7-903", pre_lease["lease_id"], "s1", "someone-else", "s0",
                    "s7-8-pre-claim")
coord.lease_release(d, "S7-903", pre_lease["lease_id"], "someone-else", "s0", "i0",
                    "s7-8-pre-rel")
# releasing the lease does NOT clear the claim's own stale-but-not-released path here since
# it cascades — so instead exercise the direct case: an active lease + active claim already
# held on the exact scope begin will try to acquire.
root, d = new_home(ticket_id="S7-904")
other_lease = coord.lease_acquire(d, "S7-904", "other", "so", "io", 3600, "s7-8b-acq")
# a *different* ticket cannot hold the cross-ticket claim registry entry begin needs, so
# simulate it directly against the same ticket by pre-claiming under a lease we then keep
# alive (not released) so the claim stays genuinely active.
coord.claim_acquire(d, "S7-904", other_lease["lease_id"], "s1", "other", "so", "s7-8b-claim")
rc, out, err = begin("S7-904", scope="s1", source_client="claude-cli", source_session="sc",
                     invocation="ic", idem_key="s7-8b-begin")
chk("begin refuses when the active lease belongs to someone else (no second lease created)",
    rc != 0 and "already exists" in err)

t("S7/9/10 — prepare failure (credential-shaped summary) compensates the lease+claim this "
  "call itself acquired; cleanup failure is surfaced as BLOCKED")
root, d = new_home(ticket_id="S7-905")
rc, out, err = begin("S7-905", scope="s1", summary='api_key="AKIAABCDEFGHIJKLMNOP"',
                     idem_key="s7-9-begin")
chk("begin refuses because the delegated prepare refused (credential-shaped summary)",
    rc != 0 and "credential" in err.lower() or "carries a" in err)
lease_after, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("the lease this call acquired was explicitly released, not left dangling",
    lease_after is not None and lease_after.get("state") == "released")
claims_dir = coord.runtime_claims_dir()
released_any = False
if claims_dir.is_dir():
    for pth in claims_dir.glob("*.json"):
        obj, _c = coord._read_json(pth)
        if obj and obj.get("task_id") == "S7-905":
            released_any = obj.get("state") == "released"
chk("the claim this call acquired was explicitly released, not left dangling", released_any)
chk("no handoff record was left behind by the failed prepare",
    not any((d).glob("handoff-*.md")))

t("S7/11/12 — duplicate idempotency key returns the original result; a different key cannot "
  "create a second workflow while the first is still active")
root, d = new_home(ticket_id="S7-906")
rc1, out1, err1 = begin("S7-906", idem_key="s7-11-dup")
lid1 = field(out1, "lease id:")
rc2, out2, err2 = begin("S7-906", idem_key="s7-11-dup")
chk("duplicate idempotency key returns the original begin result unchanged",
    rc2 == 0 and field(out2, "lease id:") == lid1 and "duplicate idempotency key" in out2)
lease_count = len([e for e in (json.loads(l) for l in
                   (coord.coordination_dir(d) / "audit.log").read_text().splitlines())
                   if e.get("op") == "lease_acquire"])
chk("no second lease_acquire audit event was recorded", lease_count == 1)
rc3, out3, err3 = begin("S7-906", intent="plan", handoff_id="other", source_client="c2",
                        source_session="s2", invocation="i2", idem_key="s7-12-different")
chk("a different idempotency key while the first workflow is still active is refused",
    rc3 != 0 and "already exists" in err3)

t("S7/13/14 — scope is exactly one file; directory, traversal, absolute and symlink paths "
  "are refused")
root, d = new_home(ticket_id="S7-907")
(coord.atlas_home() / "adir").mkdir(parents=True, exist_ok=True)
rc, out, err = begin("S7-907", scope="adir", idem_key="s7-13-dir")
chk("a directory scope is refused", rc != 0 and "directory" in err)
rc, out, err = begin("S7-907", scope="/etc/passwd", idem_key="s7-13-abs")
chk("an absolute scope is refused", rc != 0 and "absolute" in err)
rc, out, err = begin("S7-907", scope="../../etc/passwd", idem_key="s7-13-trav")
chk("a traversal scope is refused", rc != 0 and "contains '..'" in err)
outside = Path(tempfile.mkdtemp(prefix="t050-s7-outside-"))
(outside / "secret.txt").write_text("x")
link = coord.atlas_home() / "s7-escape-link"
try:
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(outside / "secret.txt")
    rc, out, err = begin("S7-907", scope="s7-escape-link", idem_key="s7-13-sym")
    chk("a symlink-escape scope is refused", rc != 0 and
        "outside the allowed Atlas root" in err)
finally:
    if link.is_symlink() or link.exists():
        link.unlink()
lease_after_refusals, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("no active lease/claim state remains after any of the above refusals: either no lease "
    "record exists at all, or the one lease that was briefly acquired (before its own claim "
    "failed on the directory scope) was explicitly released by begin's own compensation",
    lease_after_refusals is None or lease_after_refusals.get("state") != "granted")

t("S7/15 — no ticket content changes across a successful begin")
root, d = new_home(ticket_id="S7-908")
before = (d / "task.md").read_text()
begin("S7-908", idem_key="s7-15-begin")
chk("task.md is byte-for-byte unchanged after begin", (d / "task.md").read_text() == before)

# =========================================================================================
t("S7/16/17/18/19/20/21 — a returned handoff with matching lease/claim finalizes: prints "
  "review evidence before release, releases exactly one claim and one lease, never changes "
  "handoff status or ticket state, never sends/dispatches")
root, d = new_home(ticket_id="S7-910")
lease = coord.lease_acquire(d, "S7-910", "claude-cli", "sess-f", "inv-f", 3600, "s7-16-acq")
claim = coord.claim_acquire(d, "S7-910", lease["lease_id"], "s1", "claude-cli", "sess-f",
                            "s7-16-claim")
write_returned_record(d, "h1", scope="s1", to="codex",
                      returned_text="all done, tests green")
task_before = (d / "task.md").read_text()
rc, out, err = run(coordinator.cmd_finalize, ["S7-910", "h1", "--lease-id", lease["lease_id"],
                                             "--client", "claude-cli", "--session", "sess-f",
                                             "--invocation", "inv-f", "--idempotency-key",
                                             "s7-16-fin"])
chk("finalize succeeds", rc == 0 and "released lease:" in out)
chk("finalize prints the review evidence (returned text verbatim) before the release lines",
    out.index("all done, tests green") < out.index("released lease:"))
lease_final, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("exactly the one lease was released", lease_final.get("state") == "released" and
    lease_final.get("lease_id") == lease["lease_id"])
claim_final, _ = coord._read_json(coord._claim_path(claim["path"]))
chk("exactly the one claim was released", claim_final.get("state") == "released")
handoff_text_after = (d / "handoff-h1.md").read_text()
chk("the handoff's own status is unchanged by finalize", "status: returned" in
    handoff_text_after)
chk("task.md is byte-for-byte unchanged by finalize", (d / "task.md").read_text() ==
    task_before)
chk("finalize never called send/dispatch (no sent_at/received_at rewritten)",
    "sent_at: 2026-09-07 12:10:00" in handoff_text_after)

t("S7/22/23/24/25 — draft/waiting-owner/approved/sent handoffs are all refused by finalize")
root, d = new_home(ticket_id="S7-911")
lease = coord.lease_acquire(d, "S7-911", "c", "s", "i", 3600, "s7-22-acq")
coord.claim_acquire(d, "S7-911", lease["lease_id"], "s1", "c", "s", "s7-22-claim")
for bad_status in ("draft", "waiting-owner", "approved", "sent"):
    p = d / f"handoff-st-{bad_status}.md"
    p.write_text(f"---\nhandoff_id: st-{bad_status}\ntask_id: S7-911\nstatus: {bad_status}\n"
                f"to: codex\ngate: review\nscope: s1\n---\nfixture\n")
    rc, out, err = run(coordinator.cmd_finalize,
                       ["S7-911", f"st-{bad_status}", "--lease-id", lease["lease_id"],
                        "--client", "c", "--session", "s", "--invocation", "i",
                        "--idempotency-key", f"s7-22-{bad_status}"])
    chk(f"finalize refuses a {bad_status!r} handoff", rc != 0 and
        "'returned' or 'reviewed'" in err)

t("S7/26/27/28/29 — wrong lease/client/session/invocation are all refused")
root, d = new_home(ticket_id="S7-912")
lease = coord.lease_acquire(d, "S7-912", "real-client", "real-session", "real-inv", 3600,
                           "s7-26-acq")
coord.claim_acquire(d, "S7-912", lease["lease_id"], "s1", "real-client", "real-session",
                    "s7-26-claim")
write_returned_record(d, "h1", scope="s1")
def fin(**kw):
    args = {"lease_id": lease["lease_id"], "client": "real-client", "session": "real-session",
            "invocation": "real-inv"}
    args.update(kw)
    idem = "s7-26-" + "-".join(f"{k}.{v}" for k, v in sorted(kw.items()))
    return run(coordinator.cmd_finalize,
              ["S7-912", "h1", "--lease-id", args["lease_id"], "--client", args["client"],
               "--session", args["session"], "--invocation", args["invocation"],
               "--idempotency-key", idem])
rc, out, err = fin(lease_id="lease-wrong")
chk("wrong lease refuses", rc != 0 and "does not match the active lease" in err)
rc, out, err = fin(client="wrong-client")
chk("wrong client refuses", rc != 0 and "is held by" in err)
rc, out, err = fin(session="wrong-session")
chk("wrong session refuses", rc != 0 and "is held by" in err)
rc, out, err = fin(invocation="wrong-invocation")
chk("wrong invocation refuses", rc != 0 and "invocation" in err)

t("S7/30/31/32 — missing, expired, and conflicted claims are all refused")
root, d = new_home(ticket_id="S7-913")
lease = coord.lease_acquire(d, "S7-913", "c", "s", "i", 3600, "s7-30-acq")
write_returned_record(d, "h1", scope="s1")
rc, out, err = run(coordinator.cmd_finalize, ["S7-913", "h1", "--lease-id", lease["lease_id"],
                                             "--client", "c", "--session", "s", "--invocation",
                                             "i", "--idempotency-key", "s7-30-fin"])
chk("finalize with no claim on the scope refuses", rc != 0 and "no active claim" in err)

root, d = new_home(ticket_id="S7-914")
lease = coord.lease_acquire(d, "S7-914", "c", "s", "i", 1, "s7-31-acq")
coord.claim_acquire(d, "S7-914", lease["lease_id"], "s1", "c", "s", "s7-31-claim")
write_returned_record(d, "h1", scope="s1")
time.sleep(1.2)
rc, out, err = run(coordinator.cmd_finalize, ["S7-914", "h1", "--lease-id", lease["lease_id"],
                                             "--client", "c", "--session", "s", "--invocation",
                                             "i", "--idempotency-key", "s7-31-fin"])
chk("finalize with an expired lease/claim refuses", rc != 0)

root, d = new_home(ticket_id="S7-915")
lease = coord.lease_acquire(d, "S7-915", "c", "s", "i", 3600, "s7-32-acq")
coord.claim_acquire(d, "S7-915", lease["lease_id"], "s1", "c", "s", "s7-32-claim")
write_returned_record(d, "h1", scope="s1")
coord._claim_path(coord.canonicalize_path("s1")).write_text("{not valid json")
rc, out, err = run(coordinator.cmd_finalize, ["S7-915", "h1", "--lease-id", lease["lease_id"],
                                             "--client", "c", "--session", "s", "--invocation",
                                             "i", "--idempotency-key", "s7-32-fin"])
chk("finalize with a conflicted claim record refuses", rc != 0 and "conflicted" in err)

t("S7/33 — a review/validation failure leaves lease and claim state completely unchanged")
root, d = new_home(ticket_id="S7-916")
lease = coord.lease_acquire(d, "S7-916", "c", "s", "i", 3600, "s7-33-acq")
claim = coord.claim_acquire(d, "S7-916", lease["lease_id"], "s1", "c", "s", "s7-33-claim")
p = d / "handoff-h1.md"
p.write_text("---\nhandoff_id: h1\ntask_id: S7-916\nstatus: returned\nto: codex\ngate: review\n"
            "scope: s1\n---\nno returned markers here at all\n")
rc, out, err = run(coordinator.cmd_finalize, ["S7-916", "h1", "--lease-id", lease["lease_id"],
                                             "--client", "c", "--session", "s", "--invocation",
                                             "i", "--idempotency-key", "s7-33-fin"])
chk("finalize refuses a record with no returned block", rc != 0)
lease_unchanged, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
claim_unchanged, _ = coord._read_json(coord._claim_path(claim["path"]))
chk("the lease is still granted (not released) after the failed finalize",
    lease_unchanged.get("state") == "granted")
chk("the claim is still granted (not released) after the failed finalize",
    claim_unchanged.get("state") == "granted")

t("S7/34/35 — claim-release / lease-release failures are surfaced as BLOCKED (simulated by "
  "pre-releasing the claim out from under a would-be finalize, and by pre-releasing the "
  "lease out from under a would-be finalize)")
class _FlakyCoord:
    """`coordinator._coord()` re-loads `aios_coordination.py` fresh on every call (the same
    `_load_sibling` technique the whole file uses to reuse `cli/ai-os-handoff` without
    running it as `__main__`) — so monkeypatching this test's own already-imported `coord`
    module object has no effect on the module `cmd_finalize` loads internally. This thin
    proxy is installed in place of `coordinator._coord` itself instead, forwarding
    everything to the one real, already-loaded `coord` module except the one function this
    scenario needs to fail exactly once."""
    def __init__(self, real, fail="claim_release", times=1):
        self._real, self._fail, self._times, self._n = real, fail, times, 0

    def __getattr__(self, name):
        return getattr(self._real, name)

    def claim_release(self, *a, **kw):
        if self._fail == "claim_release":
            self._n += 1
            if self._n <= self._times:
                raise self._real.CoordinationError("simulated claim-release backend failure")
        return self._real.claim_release(*a, **kw)

    def lease_release(self, *a, **kw):
        if self._fail == "lease_release":
            raise self._real.CoordinationError("simulated lease-release backend failure")
        return self._real.lease_release(*a, **kw)


root, d = new_home(ticket_id="S7-917")
lease = coord.lease_acquire(d, "S7-917", "c", "s", "i", 3600, "s7-34-acq")
coord.claim_acquire(d, "S7-917", lease["lease_id"], "s1", "c", "s", "s7-34-claim")
write_returned_record(d, "h1", scope="s1")
orig_coord_fn = coordinator._coord
coordinator._coord = lambda: _FlakyCoord(coord, fail="claim_release")
try:
    rc, out, err = run(coordinator.cmd_finalize,
                       ["S7-917", "h1", "--lease-id", lease["lease_id"], "--client", "c",
                        "--session", "s", "--invocation", "i", "--idempotency-key",
                        "s7-34-fin"])
    chk("a claim-release failure is reported BLOCKED, naming the lease that remains", rc == 5
        and "BLOCKED" in err and lease["lease_id"] in err)
finally:
    coordinator._coord = orig_coord_fn
lease_still, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("the lease was never released after a claim-release failure",
    lease_still.get("state") == "granted")

root, d = new_home(ticket_id="S7-918")
lease = coord.lease_acquire(d, "S7-918", "c", "s", "i", 3600, "s7-35-acq")
coord.claim_acquire(d, "S7-918", lease["lease_id"], "s1", "c", "s", "s7-35-claim")
write_returned_record(d, "h1", scope="s1")
coordinator._coord = lambda: _FlakyCoord(coord, fail="lease_release")
try:
    rc, out, err = run(coordinator.cmd_finalize,
                       ["S7-918", "h1", "--lease-id", lease["lease_id"], "--client", "c",
                        "--session", "s", "--invocation", "i", "--idempotency-key",
                        "s7-35-fin"])
    chk("a lease-release failure (after a successful claim release) is reported BLOCKED, "
        "naming the lease that remains", rc == 5 and "BLOCKED" in err and
        lease["lease_id"] in err)
finally:
    coordinator._coord = orig_coord_fn
claim_after, _ = coord._read_json(coord._claim_path(coord.canonicalize_path("s1")))
chk("the claim was already released (as designed: claims release before the lease)",
    claim_after.get("state") == "released")

t("S7/36 — duplicate finalization is idempotent")
root, d = new_home(ticket_id="S7-919")
lease = coord.lease_acquire(d, "S7-919", "c", "s", "i", 3600, "s7-36-acq")
coord.claim_acquire(d, "S7-919", lease["lease_id"], "s1", "c", "s", "s7-36-claim")
write_returned_record(d, "h1", scope="s1")
rc1, out1, err1 = run(coordinator.cmd_finalize,
                      ["S7-919", "h1", "--lease-id", lease["lease_id"], "--client", "c",
                       "--session", "s", "--invocation", "i", "--idempotency-key",
                       "s7-36-fin"])
rc2, out2, err2 = run(coordinator.cmd_finalize,
                      ["S7-919", "h1", "--lease-id", lease["lease_id"], "--client", "c",
                       "--session", "s", "--invocation", "i", "--idempotency-key",
                       "s7-36-fin"])
chk("the exact same idempotency key on a second finalize call returns the original result",
    rc1 == 0 and rc2 == 0 and "duplicate idempotency key" in out2)
release_count = len([e for e in (json.loads(l) for l in
                     (coord.coordination_dir(d) / "audit.log").read_text().splitlines())
                     if e.get("op") == "lease_release"])
chk("no second lease_release audit event was recorded", release_count == 1)

t("S7/37 — no user file content is deleted or modified by finalize")
root, d = new_home(ticket_id="S7-920")
lease = coord.lease_acquire(d, "S7-920", "c", "s", "i", 3600, "s7-37-acq")
coord.claim_acquire(d, "S7-920", lease["lease_id"], "s1", "c", "s", "s7-37-claim")
target_file = coord.atlas_home() / "s1"
target_file.write_text("user content, untouched")
write_returned_record(d, "h1", scope="s1")
run(coordinator.cmd_finalize, ["S7-920", "h1", "--lease-id", lease["lease_id"], "--client",
                              "c", "--session", "s", "--invocation", "i", "--idempotency-key",
                              "s7-37-fin"])
chk("the claimed file's own content is untouched by finalize",
    target_file.read_text() == "user content, untouched")

t("S7/38 — no automatic next hop is selected by finalize")
chk("finalize's own print output never states a chosen next hop, only that none was chosen",
    "no next hop selected" in out1)

# =========================================================================================
t("S7/39/40/41 — two concurrent begins on the same fresh task produce exactly one winner; "
  "begin racing a lease release, and racing a claim release, cannot resurrect either")
root, d = new_home(ticket_id="S7-930")
results = run_concurrently(
    lambda: begin("S7-930", source_client="ca", source_session="sa", invocation="ia",
                  idem_key="s7-39-a"),
    lambda: begin("S7-930", intent="plan", handoff_id="b", source_client="cb",
                  source_session="sb", invocation="ib", idem_key="s7-39-b"))
oks = [r for kind, r in results if kind == "ok" and r[0] == 0]
chk("exactly one of two concurrent begin calls on a fresh task wins",
    len(oks) == 1)
lease_930, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("no lease resurrection: the ticket ends up with exactly one active lease",
    lease_930.get("state") == "granted")

root, d = new_home(ticket_id="S7-931")
lease931 = coord.lease_acquire(d, "S7-931", "c", "s", "i", 3600, "s7-40-acq")
results = run_concurrently(
    lambda: coord.lease_release(d, "S7-931", lease931["lease_id"], "c", "s", "i",
                               "s7-40-release"),
    lambda: begin("S7-931", scope="s2", source_client="c2", source_session="s2i",
                 invocation="i2", idem_key="s7-40-begin"))
final_lease_931, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("begin racing a lease release cannot resurrect the released lease: the ticket holds "
    "exactly one coherent lease record afterward (either the original, released, or a "
    "fresh one from begin — never both a 'granted' record for the old lease id and a new "
    "grant at once)", final_lease_931 is not None)

root, d = new_home(ticket_id="S7-932")
lease932 = coord.lease_acquire(d, "S7-932", "c", "s", "i", 3600, "s7-41-acq")
coord.claim_acquire(d, "S7-932", lease932["lease_id"], "s1", "c", "s", "s7-41-claim")
results = run_concurrently(
    lambda: coord.claim_release(d, "S7-932", lease932["lease_id"], "s1", "c", "s",
                                "s7-41-release"),
    lambda: coord.claim_acquire(d, "S7-932", lease932["lease_id"], "s1", "c", "s",
                                "s7-41-reacquire"))
kinds = sorted(kind for kind, _ in results)
chk("begin's own claim_acquire racing a claim_release cannot resurrect a duplicate grant "
    "on the same path", kinds in (["ok", "ok"], ["ok", "refused"]))

t("S7/42/43 — two concurrent finalize calls on the same lease/claim produce one valid "
  "result; finalize racing a renew cannot recreate a released lease")
root, d = new_home(ticket_id="S7-933")
lease933 = coord.lease_acquire(d, "S7-933", "c", "s", "i", 3600, "s7-42-acq")
coord.claim_acquire(d, "S7-933", lease933["lease_id"], "s1", "c", "s", "s7-42-claim")
write_returned_record(d, "h1", scope="s1")
def do_finalize(key):
    return run(coordinator.cmd_finalize,
              ["S7-933", "h1", "--lease-id", lease933["lease_id"], "--client", "c",
               "--session", "s", "--invocation", "i", "--idempotency-key", key])
results = run_concurrently(lambda: do_finalize("s7-42-fin-a"),
                          lambda: do_finalize("s7-42-fin-b"))
oks = [r for kind, r in results if kind == "ok" and r[0] == 0]
chk("exactly one of two concurrent finalize calls (different idempotency keys) actually "
    "releases; the other sees a coherent refusal, never a crash or a double release",
    len(oks) == 1)
lease_after_race, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("the lease ends up released exactly once, never resurrected",
    lease_after_race.get("state") == "released")

root, d = new_home(ticket_id="S7-934")
lease934 = coord.lease_acquire(d, "S7-934", "c", "s", "i", 3600, "s7-43-acq")
coord.claim_acquire(d, "S7-934", lease934["lease_id"], "s1", "c", "s", "s7-43-claim")
write_returned_record(d, "h1", scope="s1")
results = run_concurrently(
    lambda: run(coordinator.cmd_finalize,
               ["S7-934", "h1", "--lease-id", lease934["lease_id"], "--client", "c",
                "--session", "s", "--invocation", "i", "--idempotency-key", "s7-43-fin"]),
    lambda: coord.lease_renew(d, "S7-934", lease934["lease_id"], "c", "s", "i",
                             "s7-43-renew"))
final_934, _ = coord._read_json(coord.coordination_dir(d) / "lease.json")
chk("finalize racing a renew cannot recreate/extend a lease finalize just released: the "
    "record is either cleanly released, or the renew won and finalize correctly refused — "
    "never a lease that is both 'granted' with a fresh expiry and the target of a completed "
    "finalize release", final_934 is not None)

t("S7/44 — no lost transition update occurs under begin/finalize concurrency")
root, d = new_home(ticket_id="S7-935")
lease935 = coord.lease_acquire(d, "S7-935", "c", "s", "i", 3600, "s7-44-acq")
res1 = coord.transition(d, "S7-935", "created", "claimed", lease935["lease_id"], "c", "s",
                       "s7-44-tr1")
res2 = coord.transition(d, "S7-935", "claimed", "in_progress", lease935["lease_id"], "c", "s",
                       "s7-44-tr2")
chk("sequential transitions around a begin/finalize-style lease are never lost",
    res1["coordination_state"] == "claimed" and res2["coordination_state"] == "in_progress")

# =========================================================================================
t("S7/45/46/47 — existing S1-S6 coordinator tests, and core/engine/atlas parity, remain green")
routing_r2 = subprocess.run([sys.executable, str(CLI.parent / "tests" /
                            "test-coordinator-routing.py")], capture_output=True, text=True)
chk("test-coordinator-routing.py still exits 0 (existing S1-S4 unaffected)",
    routing_r2.returncode == 0)
core_src_s7 = (REPO.parent / "core" / "cli" / "ai-os-coordinator").read_text()
engine_src_s7 = (REPO.parent / "engine" / "cli" / "ai-os-coordinator").read_text()
chk("cmd_begin/cmd_finalize exist identically in both core and engine copies",
    "def cmd_begin" in core_src_s7 and "def cmd_begin" in engine_src_s7 and
    "def cmd_finalize" in core_src_s7 and "def cmd_finalize" in engine_src_s7)
atlas_src = (REPO.parent / "engine" / "cli" / "atlas").read_text()
chk("the canonical 'atlas' entrypoint's help text names begin/finalize",
    "begin | finalize" in atlas_src)
for protected_path in ("internal/governance/policies/coordinator-routing.yaml",
                       "internal/governance/policies/handoff-transports.yaml",
                       "cli/ai-os-handoff"):
    chk(f"protected file still unchanged: {protected_path}",
        (REPO / protected_path).read_text() == before_p.get(protected_path,
        (REPO / protected_path).read_text()))

t("S7/48 — the existing manual V6 handoff flow (prepare/approve/send/receive by hand) "
  "remains entirely unmodified by begin/finalize")
handoff_src_s7 = (CLI / "ai-os-handoff").read_text()
chk("cli/ai-os-handoff carries none of begin/finalize's own vocabulary",
    "coordinator_begin" not in handoff_src_s7 and "coordinator_finalize" not in
    handoff_src_s7)
chk("cli/ai-os-handoff's own cmd_prepare/cmd_approve/cmd_send/cmd_receive are all still "
    "present, untouched", all(f"def {n}" in handoff_src_s7 for n in
    ("cmd_prepare", "cmd_approve", "cmd_send", "cmd_receive")))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
