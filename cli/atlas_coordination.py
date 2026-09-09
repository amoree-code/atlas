"""atlas_coordination — T-050-S6/S6-R1: ticket leases, file ownership claims, and the
additive coordination-state layer, exactly as authorized by
`projects/atlas/tickets/T-050/T-050-S5-conflict-protection-design.md`, with the concurrency
and enforcement fixes from `T-050-S6-R1-implementation.md`.

This is a library, imported by `cli/atlas-coordinator`, never run directly. It writes durable
records under the existing ticket directory (`coordination/lease.json`,
`coordination/state.json`, `coordination/audit.log`, `coordination/idempotency/*.json`) and,
for file claims only, under the existing `$ATLAS_HOME/runtime` root
(`runtime/coordination/claims/*.json`) — the same root `atlas_tickets.atlas_runtime_dir()`
already writes to, not a new one. There is no daemon, no queue, no worker, no scheduler, no
heartbeat sweep and no background process anywhere in this file: every function here runs
once, synchronously, for the one caller that invoked it, and returns.

## Mutation guard (S6-R1, part A)

Every mutation in this file (lease acquire/renew/release/clear-stale, claim acquire/release/
clear-stale, coordination-state transition) runs inside a short-lived local mutation guard —
`fcntl.flock` (POSIX stdlib, no new dependency) on an on-disk lock file, taken with
`LOCK_EX | LOCK_NB` in a short bounded poll loop, released in a `finally`. Two lock domains
exist: a **ticket guard** (one lock file per ticket, `coordination/.mutation.lock`) for
lease/transition state, and a **claim guard** (one lock file per canonicalized path,
`runtime/coordination/claims/.<claim-key>.lock`) for the cross-ticket file-claim registry.
An operation takes whichever domain(s) the state it mutates lives in — `claim_acquire` takes
both, in that fixed order (ticket, then claim), because it both reads the ticket's lease and
mutates the global claim registry; nothing here ever acquires two ticket guards or two claim
guards at once, so this ordering cannot deadlock.

The guard is never exposed as a user-level ownership lock and never itself becomes durable
ownership state: the lock *file* persists (deleting it after use would let a second, distinct
inode's `flock` bypass the first — a well-known pitfall), but it holds no ownership record,
only a synchronization handle, and the `flock` itself is always released — in a `finally`,
and automatically by the OS if the process holding it dies, since `flock` is tied to the open
file descriptor, not a written value. If a guard cannot be acquired within the bounded wait,
the whole operation refuses (fails closed) rather than blocking indefinitely, retrying in a
loop, or proceeding unserialized.

Every write that only ever has one legitimate caller (a renew, a release, a clear-stale, a
transition) validates the caller's identity against the record's own recorded holder — read
fresh, inside the guard — before writing exactly once, via one atomic replace (write to a
temp file, `os.replace`). The guard is what makes that replace a true compare-and-swap; the
replace alone is never relied on for that. Nothing here is auto-reclaimed, auto-reassigned or
auto-approved: every stale/corrupt condition is reported and left blocked until an explicit
owner action names the exact record it applies to.

## Terminal records (S6-R1, part B)

A released or cleared lease/claim is never deleted: `release` and `clear-stale` overwrite the
record in place with a terminal `state` (`released` or `cleared`) plus the identity and
timestamp of who ended it — the only evidence that it happened, preserved on disk in addition
to the append-only audit log. A subsequent `acquire` may replace a terminal record with a
fresh one only while holding the same ticket/claim guard that read it, closing the race where
a concurrent `renew` could otherwise recreate/extend a lease a `release` had just ended.
"""
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
IDENTITY = SAFE
PATH_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-]*\Z")

LEASE_STATES = ("created", "claimed", "in_progress", "handoff_ready", "approved", "sent",
                "received", "blocked", "completed", "cancelled", "archived", "expired",
                "conflicted")

TERMINAL_LEASE_RECORD_STATES = ("released", "cleared")

# The transition table, S5 §3, verbatim. Every allowed (from, to) pair names exactly what it
# requires: an active, matching ticket lease; an explicit recorded approval reference; and/or
# non-empty evidence text. Nothing not listed here is a valid transition.
ALLOWED_TRANSITIONS = {
    ("created", "claimed"):          {"lease": True,  "approval": False, "evidence": False},
    ("claimed", "claimed"):          {"lease": True,  "approval": False, "evidence": False},
    ("claimed", "in_progress"):      {"lease": True,  "approval": False, "evidence": False},
    ("in_progress", "handoff_ready"): {"lease": True,  "approval": False, "evidence": True},
    ("handoff_ready", "approved"):   {"lease": True,  "approval": True,  "evidence": False},
    ("approved", "sent"):            {"lease": True,  "approval": False, "evidence": False},
    ("sent", "received"):            {"lease": True,  "approval": False, "evidence": False},
    ("received", "blocked"):         {"lease": True,  "approval": False, "evidence": True},
    ("blocked", "in_progress"):      {"lease": True,  "approval": False, "evidence": False},
    ("received", "completed"):       {"lease": True,  "approval": False, "evidence": True},
    ("completed", "archived"):       {"lease": False, "approval": True,  "evidence": False},
    ("cancelled", "archived"):       {"lease": False, "approval": True,  "evidence": False},
}
CANCEL_FROM = {"created", "claimed", "in_progress", "handoff_ready", "approved", "sent",
               "received", "blocked"}
SYSTEM_ONLY_STATES = {"expired", "conflicted"}


class CoordinationError(Exception):
    """One refusal, with the exit code the CLI layer should use. Never raised for anything
    that succeeded partially — every function in this file either completes one operation
    fully or raises before writing anything."""
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def refuse(message, code=2):
    raise CoordinationError(message, code)


# --- time -----------------------------------------------------------------------------
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat()


def parse_iso(s):
    try:
        return datetime.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


# --- home / storage roots ---------------------------------------------------------------
def atlas_home():
    """${ATLAS_HOME:-~/atlas} — the same resolution `atlas_tickets.atlas_runtime_dir()`
    already uses for its own writes, deliberately independent of the ticket-path resolver
    (core/engine drift between those two has already bitten this codebase once)."""
    v = os.environ.get("ATLAS_HOME")
    return Path(v) if v else Path.home() / "atlas"


def coordination_dir(task_dir):
    """Per-ticket coordination state: lease, coordination-state, audit log, idempotency
    cache, ticket mutation-guard lock. Lives under the existing ticket directory — never a
    second, parallel store."""
    return Path(task_dir) / "coordination"


def runtime_claims_dir():
    """The one cross-ticket authority for 'does any client already hold a writer claim on
    this exact file' — a file claim's identity is the canonicalized path, not any one
    ticket, so its uniqueness check cannot be scoped to a single ticket directory. This
    reuses the existing `$ATLAS_HOME/runtime` root (already written to by
    `atlas_tickets.atlas_runtime_dir()`), never a new runtime root."""
    return atlas_home() / "runtime" / "coordination" / "claims"


# --- mutation guard (S6-R1 part A) -------------------------------------------------------
_GUARD_TIMEOUT_SECONDS = 5.0
_GUARD_POLL_SECONDS = 0.02


@contextlib.contextmanager
def _guard(lock_path, label):
    """A short-lived, local, `flock`-based mutual-exclusion guard. Never a daemon, queue,
    worker or scheduler: this is one bounded, synchronous wait inside the one call that
    needed it, nothing runs in the background, and nothing here is visible to a caller as a
    lease, a lock record, or any other form of ownership — it is purely a mutex around the
    read/validate/write this file already does. Safe across a process crash: `flock` is
    released by the kernel the instant the holding process's file descriptor closes, for any
    reason, including a crash — there is no separate cleanup step and no stale lock file
    holds up a future acquisition (the *file* persists; the *lock on it* does not survive
    the process). Fails closed — refuses the whole operation — if the guard cannot be
    acquired within the bounded wait, rather than blocking indefinitely or retrying forever."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    acquired = False
    try:
        deadline = time.monotonic() + _GUARD_TIMEOUT_SECONDS
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(_GUARD_POLL_SECONDS)
        if not acquired:
            refuse(f"could not acquire the {label} mutation guard within "
                   f"{_GUARD_TIMEOUT_SECONDS}s — refusing rather than risk an unserialized "
                   f"read/validate/write")
        yield
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def ticket_guard(task_dir):
    return _guard(coordination_dir(task_dir) / ".mutation.lock", "ticket")


def claim_guard(claim_key):
    return _guard(runtime_claims_dir() / f".{claim_key}.lock", "claim")


def admissions_dir():
    """T-125: the one cross-ticket admission-record store — one JSON record per
    (client, session) admission. Mirrors `runtime_claims_dir()` exactly: same
    `$ATLAS_HOME/runtime` root, a separate sibling subdirectory, never a new root."""
    return atlas_home() / "runtime" / "coordination" / "admissions"


def admission_guard(admission_key):
    return _guard(admissions_dir() / f".{admission_key}.lock", "admission")


# --- low-level atomic file helpers -------------------------------------------------------
def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp{os.getpid()}"
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    os.replace(tmp, path)


def atomic_text_write(canonical_path, content):
    """The one place plain text is ever written to an application target under T-103's
    `apply_result` — same tmp-file-then-rename shape as `_atomic_write_json` above, so a
    crash mid-write never leaves a half-written result behind. Not underscore-prefixed:
    `atlas-coordinator`'s `apply` command calls this directly rather than reimplementing
    its own tmp+replace, so there is exactly one atomic-text-write implementation."""
    p = Path(canonical_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = p.parent / f".{p.name}.tmp{os.getpid()}"
    tmp_path.write_text(content)
    os.replace(tmp_path, p)


def _read_json(path):
    """(obj, corrupt) — obj is None and corrupt is False when the file simply does not
    exist; obj is None and corrupt is True when it exists but fails to parse as the record
    shape this file expects, which callers treat as a `conflicted` record, never a guess."""
    if not path.is_file():
        return None, False
    try:
        text = path.read_text(errors="replace")
        obj = json.loads(text)
    except (OSError, json.JSONDecodeError):
        return None, True
    if not isinstance(obj, dict):
        return None, True
    return obj, False


def _best_effort_field(path, key):
    """Used only for recovery when a record is corrupt: pull one string field out of raw
    text by regex, so `clear-stale` can still be told the exact id it must match even when
    the record's JSON no longer parses. Never used to make a grant/refuse decision on its
    own — only to name the record an owner is about to explicitly clear."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return None
    m = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]*)"', text)
    return m.group(1) if m else None


def audit_append(task_dir, event):
    """Append-only. One JSON line per grant/renew/release/clear-stale/claim/transition
    event, never overwritten, never truncated, never rewritten in place."""
    d = coordination_dir(task_dir)
    d.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("at", iso(now_utc()))
    with open(d / "audit.log", "a") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


# --- idempotency ---------------------------------------------------------------------
def _idempotency_path(task_dir, key):
    return coordination_dir(task_dir) / "idempotency" / f"{key}.json"


def idempotency_check(task_dir, key, op, target):
    """None if this key has not been seen for this task. The cached result dict if the
    same (op, target, key) was already performed — returned again, unchanged, with no
    second side effect. A refusal if the same key was already used for a *different*
    operation or target: an ambiguous replay fails closed rather than guessing which call
    the caller actually meant."""
    p = _idempotency_path(task_dir, key)
    obj, corrupt = _read_json(p)
    if obj is None:
        if corrupt:
            refuse(f"idempotency record for key {key!r} is corrupt — refusing rather than "
                   f"guessing whether this is a duplicate request")
        return None
    if obj.get("op") != op or obj.get("target") != target:
        refuse(f"idempotency key {key!r} was already used for a different operation/target "
               f"({obj.get('op')!r}/{obj.get('target')!r}) — refusing an ambiguous replay")
    return obj.get("result")


def idempotency_store(task_dir, key, op, target, result):
    p = _idempotency_path(task_dir, key)
    _atomic_write_json(p, {"op": op, "target": target, "result": result,
                           "stored_at": iso(now_utc())})


# --- identity / value validation -------------------------------------------------------
def require_identity(value, label):
    if not value or not str(value).strip():
        refuse(f"--{label} is required")
    value = value.strip()
    if not IDENTITY.fullmatch(value):
        refuse(f"not a valid {label}: {value!r} — one token of [A-Za-z0-9._-]")
    return value


def require_token(value, label):
    """Like require_identity, but for a server- or caller-facing opaque token (lease id,
    idempotency key) rather than a declared client/session identity — same shape, separate
    name so a refusal names the right field."""
    return require_identity(value, label)


def require_ttl_seconds(value):
    if value is None or not str(value).strip():
        refuse("--ttl-seconds is required")
    try:
        n = int(str(value).strip())
    except ValueError:
        refuse(f"--ttl-seconds must be a positive integer, not {value!r}")
    if n <= 0:
        refuse(f"--ttl-seconds must be a positive integer, not {value!r} — every lease has "
               f"a finite TTL")
    return n


def require_text(value, label, scan_credentials=None):
    if value is None or not str(value).strip():
        refuse(f"--{label} is required and must be non-empty")
    value = value.strip()
    if scan_credentials is not None:
        scan_credentials(value)
    return value


def gen_lease_id():
    return "lease-" + uuid.uuid4().hex


# --- ticket lease -----------------------------------------------------------------------
def _lease_path(task_dir):
    return coordination_dir(task_dir) / "lease.json"


def lease_acquire(task_dir, task_id, client, session, invocation, ttl_seconds, idem_key):
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    invocation = require_identity(invocation, "invocation")
    ttl_seconds = require_ttl_seconds(ttl_seconds)
    idem_key = require_token(idem_key, "idempotency-key")

    with ticket_guard(task_dir):
        cached = idempotency_check(task_dir, idem_key, "lease_acquire", task_id)
        if cached is not None:
            return dict(cached, replay=True)

        lease_path = _lease_path(task_dir)
        obj, corrupt = _read_json(lease_path)
        if corrupt:
            lid = _best_effort_field(lease_path, "lease_id")
            refuse(f"task {task_id} has a conflicted lease record"
                   f"{f' ({lid})' if lid else ''} — an owner must run "
                   f"'coordinator lease clear-stale {task_id} <lease-id> --owner-words "
                   f"<text>' before a new lease can be granted")
        if obj is not None and obj.get("state") == "granted":
            expires = parse_iso(obj.get("expires_at"))
            if expires is not None and now_utc() <= expires:
                refuse(f"an active lease already exists for task {task_id}: lease_id="
                       f"{obj.get('lease_id')} holder={obj.get('client_id')}/"
                       f"{obj.get('session_id')} expires_at={obj.get('expires_at')} — "
                       f"acquire refused, not queued")
            refuse(f"task {task_id} has a stale lease {obj.get('lease_id')} (expired at "
                   f"{obj.get('expires_at')}, held by {obj.get('client_id')}/"
                   f"{obj.get('session_id')}) — an owner must run 'coordinator lease "
                   f"clear-stale {task_id} {obj.get('lease_id')} --owner-words <text>' "
                   f"before a new lease can be granted")
        # obj is None (no lease ever existed), or obj carries a terminal state (released /
        # cleared) from a prior holder — either way, safe to replace, and safe *because*
        # we are still holding the ticket guard that read it: no concurrent acquire can be
        # mid-flight for this same ticket.

        lease_id = gen_lease_id()
        acquired_at = now_utc()
        expires_at = acquired_at + datetime.timedelta(seconds=ttl_seconds)
        record = {
            "lease_id": lease_id, "task_id": task_id, "client_id": client,
            "session_id": session, "invocation_id": invocation, "ttl_seconds": ttl_seconds,
            "acquired_at": iso(acquired_at), "expires_at": iso(expires_at),
            "heartbeat": iso(acquired_at), "state": "granted",
        }
        _atomic_write_json(lease_path, record)

        audit_append(task_dir, {"op": "lease_acquire", "task_id": task_id,
                                "lease_id": lease_id, "client_id": client,
                                "session_id": session, "invocation_id": invocation,
                                "expires_at": iso(expires_at)})
        result = dict(record, replay=False)
        idempotency_store(task_dir, idem_key, "lease_acquire", task_id, result)
        return result


def _load_active_lease_or_die(task_dir, task_id, check_expiry=True):
    """The one shared 'is there a currently usable lease on this ticket' check, used by
    every operation that requires an active lease (claim, transition, dispatch) except
    `lease_renew` itself, which needs its own distinct expiry-refusal wording and so checks
    expiry with `check_expiry=False` here and its own comparison right after. Must always be
    called while already holding the caller's ticket guard, so the read it performs is
    consistent with whatever the caller is about to validate/write next."""
    lease_path = _lease_path(task_dir)
    obj, corrupt = _read_json(lease_path)
    if corrupt:
        refuse(f"task {task_id} has a conflicted lease record — an owner must run "
               f"clear-stale before this lease can be used")
    if obj is None:
        refuse(f"no active lease exists for task {task_id}")
    if obj.get("state") == "released":
        refuse(f"no active lease exists for task {task_id}: lease {obj.get('lease_id')} "
               f"was released at {obj.get('released_at')} by {obj.get('released_by')}")
    if obj.get("state") == "cleared":
        refuse(f"no active lease exists for task {task_id}: lease {obj.get('lease_id')} "
               f"was cleared (stale) at {obj.get('cleared_at')}")
    if obj.get("state") != "granted":
        refuse(f"no active lease exists for task {task_id}")
    if check_expiry:
        expires = parse_iso(obj.get("expires_at"))
        if expires is None or now_utc() > expires:
            refuse(f"no active lease exists for task {task_id}: lease {obj.get('lease_id')} "
                   f"is expired (expired at {obj.get('expires_at')}) — an owner must run "
                   f"'coordinator lease clear-stale {task_id} {obj.get('lease_id')} "
                   f"--owner-words <text>' before it can be used again")
    return lease_path, obj


def lease_renew(task_dir, task_id, lease_id, client, session, invocation, idem_key):
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    invocation = require_identity(invocation, "invocation")
    idem_key = require_token(idem_key, "idempotency-key")

    with ticket_guard(task_dir):
        cached = idempotency_check(task_dir, idem_key, "lease_renew", f"{task_id}:{lease_id}")
        if cached is not None:
            return dict(cached, replay=True)

        lease_path, obj = _load_active_lease_or_die(task_dir, task_id, check_expiry=False)
        if obj.get("lease_id") != lease_id:
            refuse(f"lease_id {lease_id!r} does not match the current lease "
                   f"{obj.get('lease_id')!r} on task {task_id} — refused, not a write to "
                   f"the existing lease")
        expires = parse_iso(obj.get("expires_at"))
        if expires is None or now_utc() > expires:
            refuse(f"lease {lease_id} on task {task_id} already expired at "
                   f"{obj.get('expires_at')} — renewal after expiry is refused; request a "
                   f"new lease instead")
        if obj.get("client_id") != client:
            refuse(f"wrong client: lease {lease_id} is held by {obj.get('client_id')!r}, "
                   f"not {client!r} — refused")
        if obj.get("session_id") != session:
            refuse(f"wrong session: lease {lease_id} is held by session "
                   f"{obj.get('session_id')!r}, not {session!r} — refused")
        if obj.get("invocation_id") != invocation:
            refuse(f"wrong invocation: lease {lease_id} was acquired under invocation "
                   f"{obj.get('invocation_id')!r}, not {invocation!r} — refused")

        now = now_utc()
        new_expires = now + datetime.timedelta(seconds=int(obj["ttl_seconds"]))
        updated = dict(obj, heartbeat=iso(now), expires_at=iso(new_expires))
        _atomic_write_json(lease_path, updated)
        audit_append(task_dir, {"op": "lease_renew", "task_id": task_id, "lease_id": lease_id,
                                "client_id": client, "session_id": session,
                                "invocation_id": invocation, "expires_at": iso(new_expires)})
        result = dict(updated, replay=False)
        idempotency_store(task_dir, idem_key, "lease_renew", f"{task_id}:{lease_id}", result)
        return result


def _release_claims_for_lease(task_dir, task_id, lease_id, reason):
    """A file claim's expiry is inherited from its referencing lease alone (S5 §2.1/§2.5) —
    'a claim cannot outlive its lease'. Natural expiry is already caught by comparing `now`
    against the claim's own stored `lease_expires_at` snapshot; an *explicit* release or
    clear-stale ends the lease before that snapshot's time arrives, so this cascades that
    same ending onto every claim still referencing it, synchronously, as a direct and
    deterministic consequence of the one explicit action the caller just took — never a
    background sweep, never a recovery of anything left stale on its own. Called only from
    inside the caller's own ticket guard; takes the claim guard for each file it touches, in
    that order (ticket then claim), matching `claim_acquire`'s own ordering so the two can
    never deadlock against each other."""
    d = runtime_claims_dir()
    if not d.is_dir():
        return
    for p in sorted(d.glob("*.json")):
        obj, corrupt = _read_json(p)
        if corrupt or obj is None:
            continue
        if obj.get("task_id") != task_id or obj.get("lease_id") != lease_id:
            continue
        if obj.get("state") != "granted":
            continue
        claim_key = p.stem
        with claim_guard(claim_key):
            obj2, corrupt2 = _read_json(p)
            if corrupt2 or obj2 is None or obj2.get("state") != "granted" or \
               obj2.get("task_id") != task_id or obj2.get("lease_id") != lease_id:
                continue
            released_at = iso(now_utc())
            released_by = f"{obj2.get('client_id')}/{obj2.get('session_id')}"
            terminal = dict(obj2, state="released", released_at=released_at,
                            released_by=released_by)
            _atomic_write_json(p, terminal)
        audit_append(task_dir, {"op": "claim_release", "task_id": task_id,
                                "path": obj2.get("path"), "lease_id": lease_id,
                                "client_id": obj2.get("client_id"),
                                "session_id": obj2.get("session_id"),
                                "cascaded_from": reason})


def lease_release(task_dir, task_id, lease_id, client, session, invocation, idem_key):
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    invocation = require_identity(invocation, "invocation")
    idem_key = require_token(idem_key, "idempotency-key")

    with ticket_guard(task_dir):
        cached = idempotency_check(task_dir, idem_key, "lease_release",
                                   f"{task_id}:{lease_id}")
        if cached is not None:
            return dict(cached, replay=True)

        lease_path = _lease_path(task_dir)
        obj, corrupt = _read_json(lease_path)
        if corrupt:
            refuse(f"task {task_id} has a conflicted lease record — an owner must run "
                   f"clear-stale before it can be released")
        if obj is None:
            refuse(f"no active lease exists for task {task_id} to release")
        if obj.get("state") == "released":
            refuse(f"lease {obj.get('lease_id')} on task {task_id} was already released at "
                   f"{obj.get('released_at')} by {obj.get('released_by')} — nothing to "
                   f"release")
        if obj.get("state") == "cleared":
            refuse(f"lease {obj.get('lease_id')} on task {task_id} was already cleared "
                   f"(stale) at {obj.get('cleared_at')} — nothing to release")
        if obj.get("state") != "granted":
            refuse(f"no active lease exists for task {task_id} to release")
        if obj.get("lease_id") != lease_id:
            refuse(f"lease_id {lease_id!r} does not match the current lease "
                   f"{obj.get('lease_id')!r} on task {task_id} — refused, not a write to "
                   f"the existing lease")
        if obj.get("client_id") != client:
            refuse(f"wrong client: lease {lease_id} is held by {obj.get('client_id')!r}, "
                   f"not {client!r} — release refused")
        if obj.get("session_id") != session:
            refuse(f"wrong session: lease {lease_id} is held by session "
                   f"{obj.get('session_id')!r}, not {session!r} — release refused")
        if obj.get("invocation_id") != invocation:
            refuse(f"wrong invocation: lease {lease_id} was acquired under invocation "
                   f"{obj.get('invocation_id')!r}, not {invocation!r} — release refused")

        released_at = iso(now_utc())
        released_by = f"{client}/{session}"
        terminal = dict(obj, state="released", released_at=released_at,
                        released_by=released_by)
        _atomic_write_json(lease_path, terminal)
        audit_append(task_dir, {"op": "lease_release", "task_id": task_id,
                                "lease_id": lease_id, "client_id": client,
                                "session_id": session, "invocation_id": invocation})
        _release_claims_for_lease(task_dir, task_id, lease_id, "lease_release")
        result = {"lease_id": lease_id, "task_id": task_id, "released_by": released_by,
                 "released_at": released_at, "replay": False}
        idempotency_store(task_dir, idem_key, "lease_release", f"{task_id}:{lease_id}",
                          result)
        return result


def lease_clear_stale(task_dir, task_id, lease_id, owner_words, scan_credentials=None):
    lease_id = require_token(lease_id, "lease-id")
    owner_words = require_text(owner_words, "owner-words", scan_credentials)

    with ticket_guard(task_dir):
        lease_path = _lease_path(task_dir)
        obj, corrupt = _read_json(lease_path)
        if obj is None and not corrupt:
            refuse(f"no lease record exists for task {task_id} to clear")
        record_lease_id = obj.get("lease_id") if obj is not None else \
            _best_effort_field(lease_path, "lease_id")
        if record_lease_id != lease_id:
            refuse(f"lease id mismatch: the record for task {task_id} names "
                   f"{record_lease_id!r}, not {lease_id!r} — clear-stale requires the exact "
                   f"lease id")
        if obj is not None and obj.get("state") in TERMINAL_LEASE_RECORD_STATES:
            refuse(f"lease {lease_id} on task {task_id} was already {obj.get('state')} — "
                   f"nothing to clear-stale")

        reason = "conflicted"
        if not corrupt:
            expires = parse_iso(obj.get("expires_at"))
            if obj.get("state") == "granted" and expires is not None and now_utc() <= expires:
                refuse(f"lease {lease_id} on task {task_id} is still active (holder "
                       f"{obj.get('client_id')}/{obj.get('session_id')}, expires "
                       f"{obj.get('expires_at')}) — clear-stale is only for a stale or "
                       f"conflicted record, never to evict a live holder")
            reason = "stale"

        cleared_at = iso(now_utc())
        terminal = dict(obj if obj else {}, lease_id=lease_id, task_id=task_id,
                        state="cleared", cleared_at=cleared_at, cleared_reason=reason,
                        owner_words=owner_words)
        _atomic_write_json(lease_path, terminal)
        audit_append(task_dir, {"op": "lease_clear_stale", "task_id": task_id,
                                "lease_id": lease_id, "owner_words": owner_words,
                                "cleared_reason": reason})
        _release_claims_for_lease(task_dir, task_id, lease_id, "lease_clear_stale")
        return {"lease_id": lease_id, "task_id": task_id, "cleared_reason": reason,
               "cleared_at": cleared_at}


# --- file ownership claims ---------------------------------------------------------------
def canonicalize_path(raw_path):
    if raw_path is None or not raw_path.strip():
        refuse("--path is required and must be non-empty")
    raw_path = raw_path.strip()
    if raw_path.startswith("/") or raw_path.startswith("~"):
        refuse(f"--path {raw_path!r} is an absolute path — a claim path must be relative to "
               f"the Atlas workspace root")
    if any(part == ".." for part in raw_path.split("/")):
        refuse(f"--path {raw_path!r} contains '..' — traversal is refused")
    if not PATH_SAFE.fullmatch(raw_path):
        refuse(f"--path {raw_path!r} is not a safe relative path — [A-Za-z0-9._/-] only, no "
               f"shell characters, no empty segments")
    home = atlas_home()
    home_real = Path(os.path.realpath(str(home)))
    candidate = home / raw_path
    real = Path(os.path.realpath(str(candidate)))
    try:
        real.relative_to(home_real)
    except ValueError:
        refuse(f"--path {raw_path!r} resolves to {real}, outside the allowed Atlas root "
               f"{home_real} — refused before it reaches claim logic")
    if real.is_dir():
        refuse(f"--path {raw_path!r} is a directory — claims are always file-scoped, never "
               f"directory-scoped")
    return str(real)


def _claim_key(canonical_path):
    return hashlib.sha256(canonical_path.encode()).hexdigest()


def _claim_path(canonical_path):
    return runtime_claims_dir() / f"{_claim_key(canonical_path)}.json"


def claim_acquire(task_dir, task_id, lease_id, raw_path, client, session, idem_key):
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    idem_key = require_token(idem_key, "idempotency-key")
    canonical = canonicalize_path(raw_path)
    claim_key = _claim_key(canonical)

    with ticket_guard(task_dir):
        cached = idempotency_check(task_dir, idem_key, "claim_acquire",
                                   f"{task_id}:{canonical}")
        if cached is not None:
            return dict(cached, replay=True)

        _, lease = _load_active_lease_or_die(task_dir, task_id)
        if lease.get("lease_id") != lease_id:
            refuse(f"lease_id {lease_id!r} does not match the active lease "
                   f"{lease.get('lease_id')!r} on task {task_id} — a file claim requires "
                   f"the exact currently active ticket lease")
        if lease.get("client_id") != client or lease.get("session_id") != session:
            refuse(f"the active lease on task {task_id} is held by "
                   f"{lease.get('client_id')}/{lease.get('session_id')}, not "
                   f"{client}/{session} — a file claim requires the lease holder to be the "
                   f"requester")
        lease_expires_at = lease.get("expires_at")

        with claim_guard(claim_key):
            claim_path = _claim_path(canonical)
            existing, corrupt = _read_json(claim_path)
            if corrupt:
                refuse(f"path {canonical} has a conflicted claim record — an owner must run "
                       f"'coordinator claim clear-stale {task_id} {raw_path} --owner-words "
                       f"<text>' before a new claim can be granted")
            if existing is not None and existing.get("state") == "granted":
                held_expires = parse_iso(existing.get("lease_expires_at"))
                if held_expires is not None and now_utc() <= held_expires:
                    # T-103: conflict evidence for a live writer-vs-writer conflict — the
                    # losing side's own refusal message (below) is unchanged; this only
                    # adds a durable record of the same fact, same append-only audit log
                    # every other coordination event already goes to.
                    audit_append(task_dir, {
                        "op": "claim_conflict", "task_id": task_id, "path": canonical,
                        "requested_by": f"{client}/{session}",
                        "held_by": f"{existing.get('client_id')}/"
                                  f"{existing.get('session_id')}",
                        "held_under_lease": existing.get("lease_id"),
                        "held_under_task": existing.get("task_id"),
                        "decision": "deny",
                    })
                    refuse(f"path {canonical} is already claimed by "
                           f"{existing.get('client_id')}/{existing.get('session_id')} under "
                           f"lease {existing.get('lease_id')} (task "
                           f"{existing.get('task_id')}), expiring "
                           f"{existing.get('lease_expires_at')} — acquire refused, not "
                           f"queued")
                refuse(f"path {canonical} has a stale claim (holder "
                       f"{existing.get('client_id')}/{existing.get('session_id')}, its lease "
                       f"expired at {existing.get('lease_expires_at')}) — an owner must run "
                       f"'coordinator claim clear-stale {existing.get('task_id')} "
                       f"{existing.get('raw_path')} --owner-words <text>' before a new claim "
                       f"can be granted")
            # existing is None (never claimed), or carries a terminal state (released /
            # cleared) — safe to replace while still holding both guards.

            record = {"path": canonical, "raw_path": raw_path, "task_id": task_id,
                     "lease_id": lease_id, "client_id": client, "session_id": session,
                     "acquired_at": iso(now_utc()), "lease_expires_at": lease_expires_at,
                     "state": "granted"}
            _atomic_write_json(claim_path, record)

        audit_append(task_dir, {"op": "claim_acquire", "task_id": task_id, "path": canonical,
                                "lease_id": lease_id, "client_id": client,
                                "session_id": session})
        result = dict(record, replay=False)
        idempotency_store(task_dir, idem_key, "claim_acquire", f"{task_id}:{canonical}",
                          result)
        return result


def claim_release(task_dir, task_id, lease_id, raw_path, client, session, idem_key):
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    idem_key = require_token(idem_key, "idempotency-key")
    canonical = canonicalize_path(raw_path)
    claim_key = _claim_key(canonical)

    with claim_guard(claim_key):
        cached = idempotency_check(task_dir, idem_key, "claim_release",
                                   f"{task_id}:{canonical}")
        if cached is not None:
            return dict(cached, replay=True)

        claim_path = _claim_path(canonical)
        obj, corrupt = _read_json(claim_path)
        if corrupt:
            refuse(f"path {canonical} has a conflicted claim record — an owner must run "
                   f"clear-stale before it can be released or reacquired")
        if obj is None:
            refuse(f"no active claim exists on {canonical} for task {task_id}")
        if obj.get("state") in ("released", "cleared"):
            refuse(f"the claim on {canonical} was already {obj.get('state')} — nothing to "
                   f"release")
        if obj.get("state") != "granted":
            refuse(f"no active claim exists on {canonical} for task {task_id}")
        if obj.get("task_id") != task_id or obj.get("lease_id") != lease_id:
            refuse(f"path {canonical} is claimed under task {obj.get('task_id')} / lease "
                   f"{obj.get('lease_id')}, not {task_id} / {lease_id} — release refused")
        if obj.get("client_id") != client or obj.get("session_id") != session:
            refuse(f"path {canonical} is claimed by {obj.get('client_id')}/"
                   f"{obj.get('session_id')}, not {client}/{session} — release refused")

        released_at = iso(now_utc())
        released_by = f"{client}/{session}"
        terminal = dict(obj, state="released", released_at=released_at,
                        released_by=released_by)
        _atomic_write_json(claim_path, terminal)
        audit_append(task_dir, {"op": "claim_release", "task_id": task_id,
                                "path": canonical, "lease_id": lease_id,
                                "client_id": client, "session_id": session})
        result = {"path": canonical, "task_id": task_id, "released_by": released_by,
                 "released_at": released_at, "replay": False}
        idempotency_store(task_dir, idem_key, "claim_release", f"{task_id}:{canonical}",
                          result)
        return result


def claim_clear_stale(task_dir, task_id, raw_path, owner_words, scan_credentials=None):
    owner_words = require_text(owner_words, "owner-words", scan_credentials)
    canonical = canonicalize_path(raw_path)
    claim_key = _claim_key(canonical)

    with claim_guard(claim_key):
        claim_path = _claim_path(canonical)
        obj, corrupt = _read_json(claim_path)
        if obj is None and not corrupt:
            refuse(f"no claim exists on {canonical} to clear")
        record_task_id = obj.get("task_id") if obj is not None else \
            _best_effort_field(claim_path, "task_id")
        if record_task_id != task_id:
            refuse(f"path {canonical} is claimed under task {record_task_id!r}, not "
                   f"{task_id!r} — clear-stale requires the exact task id the claim belongs "
                   f"to")
        if obj is not None and obj.get("state") in ("released", "cleared"):
            refuse(f"the claim on {canonical} was already {obj.get('state')} — nothing to "
                   f"clear-stale")

        reason = "conflicted"
        if not corrupt:
            lease_path = _lease_path(task_dir)
            lease, lease_corrupt = _read_json(lease_path)
            claim_lease_id = obj.get("lease_id")
            if not lease_corrupt and lease is not None and \
               lease.get("lease_id") == claim_lease_id and lease.get("state") == "granted":
                expires = parse_iso(lease.get("expires_at"))
                if expires is not None and now_utc() <= expires:
                    refuse(f"the claim on {canonical} is still backed by an active lease "
                           f"({claim_lease_id}, expires {lease.get('expires_at')}) — "
                           f"clear-stale is only for a stale or conflicted claim, never to "
                           f"evict a live writer")
            reason = "stale"

        cleared_at = iso(now_utc())
        terminal = dict(obj if obj else {}, task_id=task_id, path=canonical, state="cleared",
                        cleared_at=cleared_at, cleared_reason=reason, owner_words=owner_words)
        _atomic_write_json(claim_path, terminal)

    audit_append(task_dir, {"op": "claim_clear_stale", "task_id": task_id, "path": canonical,
                            "owner_words": owner_words, "cleared_reason": reason})
    return {"path": canonical, "task_id": task_id, "cleared_reason": reason,
           "cleared_at": cleared_at}


# --- coordination-state transitions ------------------------------------------------------
def _state_path(task_dir):
    return coordination_dir(task_dir) / "state.json"


def current_coordination_state(task_dir):
    obj, corrupt = _read_json(_state_path(task_dir))
    if corrupt:
        return "conflicted"
    if obj is None:
        return "created"
    return obj.get("coordination_state", "created")


def transition(task_dir, task_id, from_state, to_state, lease_id, client, session, idem_key,
              approval_ref=None, evidence=None, scan_credentials=None):
    if from_state not in LEASE_STATES:
        refuse(f"--from {from_state!r} is not a known coordination state — one of: "
               f"{', '.join(LEASE_STATES)}")
    if to_state not in LEASE_STATES:
        refuse(f"--to {to_state!r} is not a known coordination state — one of: "
               f"{', '.join(LEASE_STATES)}")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    lease_id = require_token(lease_id, "lease-id")
    idem_key = require_token(idem_key, "idempotency-key")

    if to_state in SYSTEM_ONLY_STATES:
        refuse(f"{to_state!r} is a system-observed condition, never a client-requested "
               f"transition — refused")

    with ticket_guard(task_dir):
        # Idempotency is checked before the current-state comparison below: a *repeated*
        # call with the same key must return its original result unchanged even though the
        # ticket's coordination state has, by design, already moved on since the first call
        # succeeded — otherwise a legitimate replay would be misread as a stale/ambiguous
        # request. Both checks run inside the same guard as the read/validate/write below,
        # so a concurrent transition can never land between this check and that write.
        cached = idempotency_check(task_dir, idem_key, "transition",
                                   f"{task_id}:{from_state}:{to_state}")
        if cached is not None:
            return dict(cached, replay=True)

        state_path = _state_path(task_dir)
        cur_obj, corrupt = _read_json(state_path)
        if corrupt:
            refuse(f"task {task_id} has a conflicted coordination-state record — an owner "
                   f"must resolve it before any further transition is accepted")
        cur_state = cur_obj.get("coordination_state", "created") if cur_obj is not None \
            else "created"
        if cur_state != from_state:
            refuse(f"task {task_id}'s current coordination state is {cur_state!r}, not "
                   f"{from_state!r} — refusing an ambiguous or stale transition request")

        override = False
        if to_state == "cancelled" and from_state in CANCEL_FROM:
            reqs = {"lease": True, "approval": False, "evidence": True}
            override = bool(approval_ref and approval_ref.strip())
        elif (from_state, to_state) in ALLOWED_TRANSITIONS:
            reqs = ALLOWED_TRANSITIONS[(from_state, to_state)]
        else:
            refuse(f"{from_state} -> {to_state} is not an allowed transition — refused as "
                   f"an invalid transition, not silently no-op'd and not guessed to the "
                   f"nearest valid one")

        if reqs["lease"]:
            lease_path, lease = _load_active_lease_or_die(task_dir, task_id)
            if lease.get("lease_id") != lease_id:
                refuse(f"lease_id {lease_id!r} does not match the active lease "
                       f"{lease.get('lease_id')!r} on task {task_id} — refused")
            expires = parse_iso(lease.get("expires_at"))
            if expires is None or now_utc() > expires:
                refuse(f"lease {lease_id} on task {task_id} is expired — this transition "
                       f"requires an active, matching lease")
            if not override:
                if lease.get("client_id") != client or lease.get("session_id") != session:
                    refuse(f"the active lease on task {task_id} is held by "
                           f"{lease.get('client_id')}/{lease.get('session_id')}, not "
                           f"{client}/{session} — refused (an owner override for "
                           f"cancellation requires an explicit --approval-ref)")

        if reqs["approval"] or (to_state == "cancelled" and override):
            approval_ref = require_text(approval_ref, "approval-ref", scan_credentials)
        if reqs["evidence"]:
            evidence = require_text(evidence, "evidence", scan_credentials)

        new_record = {
            "task_id": task_id, "coordination_state": to_state, "previous_state": from_state,
            "updated_at": iso(now_utc()),
            "last_transition": {"from": from_state, "to": to_state, "lease_id": lease_id,
                                "client_id": client, "session_id": session,
                                "approval_ref": approval_ref, "evidence": evidence},
        }
        _atomic_write_json(state_path, new_record)
        audit_append(task_dir, {"op": "transition", "task_id": task_id, "from": from_state,
                                "to": to_state, "lease_id": lease_id, "client_id": client,
                                "session_id": session, "approval_ref": approval_ref,
                                "evidence": evidence})
        result = dict(new_record, replay=False)
        idempotency_store(task_dir, idem_key, "transition",
                          f"{task_id}:{from_state}:{to_state}", result)
        return result


# --- T-050-S6-R1 part D: dispatch conflict-protection enforcement ------------------------
_SCOPE_MULTI_FILE_SHAPE = re.compile(r"[,\;\n]|\s")


def resolve_scope_paths(scope):
    """The handoff record's own `scope` field, resolved to the plain relative file path(s)
    dispatch's claim-enforcement preflight must check. Only a single relative path is a
    supported representation today (the existing `SCOPE_SAFE` shape `cli/atlas-coordinator`
    already validates at `route`/`prepare` time) — this does not invent a new multi-file
    scope syntax. A scope that looks like an attempt at one (comma/semicolon/newline/space-
    separated) is refused clearly rather than silently treated as one path or silently
    expanded into a directory's descendants."""
    if scope is None or not str(scope).strip():
        refuse("the handoff record has no scope — dispatch cannot verify file claims "
               "against an empty scope")
    scope = str(scope).strip()
    if _SCOPE_MULTI_FILE_SHAPE.search(scope):
        refuse(f"scope {scope!r} looks like an unsupported multi-file form (comma/"
               f"semicolon/newline/space-separated) — this slice supports only a single "
               f"plain relative file path in scope; refusing rather than guessing how to "
               f"split it or silently expanding it")
    return [scope]


def verify_dispatch_conflict_protection(task_dir, task_id, scope, lease_id, client, session):
    """The one enforcement gate `coordinator dispatch` applies before it calls the existing
    `atlas handoff send` — never applied to that command directly, and never to any other
    direct filesystem write. Read-only: writes nothing, acquires nothing, never auto-
    acquires a lease or claim it finds missing, and never falls back to a different client.
    Refuses on the first check that fails; every check after that point never runs."""
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")

    _, lease = _load_active_lease_or_die(task_dir, task_id)
    if lease.get("lease_id") != lease_id:
        refuse(f"--lease-id {lease_id!r} does not match the active lease "
               f"{lease.get('lease_id')!r} on task {task_id} — dispatch refused")
    if lease.get("client_id") != client or lease.get("session_id") != session:
        refuse(f"the active lease on task {task_id} is held by "
               f"{lease.get('client_id')}/{lease.get('session_id')}, not {client}/{session} "
               f"— dispatch refused")

    for raw_path in resolve_scope_paths(scope):
        canonical = canonicalize_path(raw_path)
        claim_path = _claim_path(canonical)
        obj, corrupt = _read_json(claim_path)
        if corrupt:
            refuse(f"path {canonical} (scope {raw_path!r}) has a conflicted claim record — "
                   f"dispatch refused")
        if obj is None:
            refuse(f"path {canonical} (scope {raw_path!r}) has no active claim — dispatch "
                   f"requires an active claim on every file in scope and never auto-"
                   f"acquires one")
        if obj.get("state") != "granted":
            refuse(f"path {canonical} (scope {raw_path!r}) has no active claim (its record "
                   f"is {obj.get('state')!r}) — dispatch refused")
        if obj.get("task_id") != task_id:
            refuse(f"path {canonical} (scope {raw_path!r}) is claimed under task "
                   f"{obj.get('task_id')!r}, not {task_id!r} — cross-ticket-inconsistent "
                   f"claim, dispatch refused")
        if obj.get("lease_id") != lease_id:
            refuse(f"path {canonical} (scope {raw_path!r}) is claimed under lease "
                   f"{obj.get('lease_id')!r}, not the supplied {lease_id!r} — dispatch "
                   f"refused")
        if obj.get("client_id") != client or obj.get("session_id") != session:
            refuse(f"path {canonical} (scope {raw_path!r}) is claimed by "
                   f"{obj.get('client_id')}/{obj.get('session_id')}, not {client}/{session} "
                   f"— dispatch refused")
        held_expires = parse_iso(obj.get("lease_expires_at"))
        if held_expires is None or now_utc() > held_expires:
            refuse(f"path {canonical} (scope {raw_path!r}) has an expired/stale claim — "
                   f"dispatch refused")
    return True


# --- T-103: revision-checked result application ------------------------------------------
# The one new enforcement entry point this ticket adds, and it is a composition of two
# calls that already exist and are already exercised by two other callers (`coordinator
# dispatch`/`finalize`): `verify_dispatch_conflict_protection` (is there a valid, matching,
# unexpired claim on this path under the currently active lease — read-only, unmodified,
# reused exactly) and `claim_release` (release it, with evidence — also unmodified, reused
# exactly). Nothing here is a second lock, a second claim store, or a second lease
# lifecycle. The one genuinely new check is a base-revision comparison: does the caller's
# declared base revision (a sha256 of the target path's content at the moment it was read)
# still match the path's current content, so a write can never silently land on top of a
# change it never saw.
EMPTY_REVISION = "0" * 64  # sentinel: "this path had no content when the writer read it"
_REVISION_RE = re.compile(r"^[0-9a-f]{64}$")


def current_revision(raw_path):
    """sha256 of `raw_path`'s current bytes, or EMPTY_REVISION if it does not exist yet.
    Computed fresh on every call, never cached or stored — staleness is only ever answered
    by looking at the file as it is right now."""
    canonical = canonicalize_path(raw_path)
    p = Path(canonical)
    if not p.is_file():
        return EMPTY_REVISION
    return hashlib.sha256(p.read_bytes()).hexdigest()


def require_revision(value, label="base-revision"):
    """A result packet's declared base revision: 64 lowercase hex characters (a sha256
    digest), or EMPTY_REVISION for 'the path had no content when I read it'. Never
    inferred, never defaulted — a missing or malformed value is refused outright, the same
    treatment every other identity/token field in this file already gets."""
    if value is None or not str(value).strip():
        refuse(f"--{label} is required — a result packet must identify its base revision, "
               f"never an inferred one")
    value = value.strip().lower()
    if value != EMPTY_REVISION and not _REVISION_RE.fullmatch(value):
        refuse(f"--{label} {value!r} is not a valid revision — 64 lowercase hex characters "
               f"(a sha256 digest), or {EMPTY_REVISION!r} for 'no prior content'")
    return value


def apply_result(task_dir, task_id, lease_id, raw_path, client, session, base_revision,
                 apply_fn, release_idem_key):
    """Apply one writer's result to `raw_path`, gated on both an active matching claim and
    a fresh base revision — refusing before `apply_fn` is ever called, and always
    releasing any claim it actually held, on every path out of this function.

    Order, and why: (1) `verify_dispatch_conflict_protection` — refuses a conflicting or
    unmatched claim, or an inactive/mismatched lease, exactly as `dispatch`/`finalize`
    already require, with conflict evidence recorded here (that function stays read-only
    and unmodified for its two existing callers). A refusal here means the caller never
    had a valid claim to begin with, so nothing is released. (2) the base-revision
    comparison — refuses a stale result, with evidence recorded. Unlike (1), a stale
    result still means the caller HELD a valid, matching claim (or step 1 would have
    already refused it), so that claim is released here too, with release evidence,
    before the stale refusal is raised — a stale-but-otherwise-valid claim is never left
    dangling. (3) only once both pass does `apply_fn` run, exactly once; whether it
    returns or raises, the claim is released right after, same as (2). Every release
    attempt in this function goes through the existing `claim_release`, and a failure
    releasing the claim is never swallowed: it is recorded and raised, with the
    stale/refusal or `apply_fn` context it happened during preserved in the message.
    """
    lease_id = require_token(lease_id, "lease-id")
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    base_revision = require_revision(base_revision)

    try:
        verify_dispatch_conflict_protection(task_dir, task_id, raw_path, lease_id, client,
                                            session)
    except CoordinationError as exc:
        audit_append(task_dir, {"op": "apply_result_conflict", "task_id": task_id,
                                "path": raw_path, "lease_id": lease_id,
                                "client_id": client, "session_id": session,
                                "decision": "deny", "reason": str(exc)})
        raise

    current = current_revision(raw_path)
    if current != base_revision:
        audit_append(task_dir, {"op": "apply_result_stale", "task_id": task_id,
                                "path": raw_path, "lease_id": lease_id,
                                "client_id": client, "session_id": session,
                                "base_revision": base_revision, "current_revision": current,
                                "decision": "deny"})
        stale_message = (f"path {raw_path} is at revision {current}, not this result's "
                        f"base revision {base_revision} — refused as stale, never applied, "
                        f"never merged")
        # A stale result still means the caller HELD a valid, matching claim (verified
        # above) — so it is released here too, same as every other exit from this
        # function, per the same evidence trail `claim_release` already writes. This is
        # distinct from the conflict branch above, which never got a claim to release.
        try:
            claim_release(task_dir, task_id, lease_id, raw_path, client, session,
                          release_idem_key)
        except CoordinationError as release_exc:
            audit_append(task_dir, {"op": "apply_result_release_failed", "task_id": task_id,
                                    "path": raw_path, "lease_id": lease_id,
                                    "client_id": client, "session_id": session,
                                    "apply_error": stale_message,
                                    "release_error": str(release_exc)})
            refuse(
                f"{stale_message} — additionally, releasing the claim on {raw_path} then "
                f"also failed ({release_exc}); neither failure is swallowed, the claim may "
                f"still be held and needs an owner to look at it directly"
            )
        refuse(stale_message)

    try:
        outcome = apply_fn()
    except Exception as exc:
        try:
            claim_release(task_dir, task_id, lease_id, raw_path, client, session,
                          release_idem_key)
        except CoordinationError as release_exc:
            audit_append(task_dir, {"op": "apply_result_release_failed", "task_id": task_id,
                                    "path": raw_path, "lease_id": lease_id,
                                    "client_id": client, "session_id": session,
                                    "apply_error": str(exc),
                                    "release_error": str(release_exc)})
            raise CoordinationError(
                f"apply_fn failed ({exc!r}) and releasing the claim on {raw_path} then "
                f"also failed ({release_exc}) — neither failure is swallowed; the claim "
                f"may still be held and needs an owner to look at it directly"
            ) from exc
        audit_append(task_dir, {"op": "apply_result", "task_id": task_id, "path": raw_path,
                                "lease_id": lease_id, "client_id": client,
                                "session_id": session, "base_revision": base_revision,
                                "decision": "failed", "reason": str(exc)})
        raise

    claim_release(task_dir, task_id, lease_id, raw_path, client, session, release_idem_key)
    new_revision = current_revision(raw_path)
    audit_append(task_dir, {"op": "apply_result", "task_id": task_id, "path": raw_path,
                            "lease_id": lease_id, "client_id": client, "session_id": session,
                            "base_revision": base_revision, "new_revision": new_revision,
                            "decision": "applied", "reason": "applied and released"})
    return {"path": raw_path, "base_revision": base_revision, "new_revision": new_revision,
           "outcome": outcome}
