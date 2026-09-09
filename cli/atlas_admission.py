"""atlas_admission — T-125: the one fail-closed admission boundary for every write-capable
AI client. Library only, imported by client hooks / provider wiring; never run directly.

This is a composition of primitives that already exist, not a new authority:

  verify_admission(task_dir, task_id, run_id, scope, client, session) checks, in order,
  refusing on the first failure and never continuing past it:

    1. atlas-agentic's `load_run` + `validate_envelope` — the run exists and its envelope
       is well-formed.
    2. the run's own `status` is "active" (not paused/blocked/completed/failed/stopped).
    3. actor identity — `actor.client` / `actor.session_id` match the caller exactly.
    4. ticket match — `goal.ticket` equals the caller's declared `task_id` exactly.
    5. exact-scope match — `claims.scope` equals the caller's declared scope, verbatim
       (never resolved, never fuzzy-matched, never a directory expansion).
    6. `atlas_coordination.verify_dispatch_conflict_protection` — the run's own bound
       `claims.lease` actually holds an active, matching ticket lease and file claim,
       right now — reused exactly as `atlas-coordinator dispatch` already requires it,
       never reimplemented.

  admit_open / admit_check / admit_close persist one JSON record per (client, session)
  under `atlas_coordination.admissions_dir()`, guarded by `admission_guard()` — the same
  atomic-write, flock-guarded, terminal-record shape every other record in
  `atlas_coordination.py` already uses. Nothing here is a second lease, a second claim
  registry, or a new source of authority.

  verify_write(client, session, write_path) is the per-write enforcement point a provider
  hook calls before an actual file write reaches disk. It trusts nothing the caller merely
  asserts about its own task/run/scope: it looks up the caller's own open admission record
  by (client, session) alone, re-runs the full verify_admission chain above against live
  state (an admission opened a minute ago is not assumed still valid), and then refuses
  unless write_path resolves to exactly the admitted scope's canonical path — the same
  exact, non-fuzzy, single-file match verify_admission already applies to the declared
  scope, never a directory expansion or a prefix match. Fail-closed: missing admission,
  closed/expired admission, wrong session, or an out-of-scope path are all refused.
"""
import os
import subprocess
import sys
from pathlib import Path
from importlib.machinery import SourceFileLoader
import importlib.util

CLI_DIR = Path(__file__).resolve().parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import atlas_coordination as coord
from atlas_coordination import (
    CoordinationError, refuse, require_identity, now_utc, iso, _atomic_write_json, _read_json,
)


def _load_agentic():
    """Loads `cli/atlas-agentic` fresh on every call, deliberately never cached at module
    scope. `atlas-agentic` bakes `$ATLAS_HOME` into a module-level constant the instant it
    is imported (`_ATLAS_HOME`/`RUNTIME_DIR`); caching the loaded module here would make
    every admission check after the first one in a given process see whichever
    `ATLAS_HOME` happened to be set at first import, not the one in effect right now. A
    fresh, uncached load costs one re-exec of that file per admission check — an
    intentionally paid cost for correctness, not a hot path."""
    src = CLI_DIR / "atlas-agentic"
    spec = importlib.util.spec_from_loader("_atlas_agentic_admission",
                                           SourceFileLoader("_atlas_agentic_admission",
                                                            str(src)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _admission_key(client, session):
    return f"{client}__{session}"


def _admission_path(client, session):
    return coord.admissions_dir() / f"{_admission_key(client, session)}.json"


def _load_run_or_refuse(agentic, run_id):
    """`atlas-agentic`'s own `run_path`/`load_run` refuse via `die()`/`sys.exit`, not
    `CoordinationError`, for a missing or malformed run id — a real inconsistency between
    the two files, not smoothed over here. Admission callers need exactly one exception
    type to catch, so this converts that `SystemExit` into a `CoordinationError` carrying
    the same message; `atlas-agentic`'s own behavior is untouched."""
    try:
        rec, path = agentic.load_run(run_id)
    except SystemExit as exc:
        refuse(f"admission refused: could not load run {run_id!r} ({exc})")
    return rec, path


def verify_admission(task_dir, task_id, run_id, scope, client, session):
    """Read-only. Raises `CoordinationError` on the first failing check; every check after
    that point never runs. Returns `(run_record, lease_id)` on success so a caller
    (`admit_open`) never has to re-derive either."""
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    if not run_id or not str(run_id).strip():
        refuse("--run-id is required for admission")
    run_id = str(run_id).strip()
    if not scope or not str(scope).strip():
        refuse("--scope is required for admission")
    scope = str(scope).strip()

    agentic = _load_agentic()
    rec, _ = _load_run_or_refuse(agentic, run_id)
    errors = agentic.validate_envelope(rec)
    if errors:
        refuse(f"run {run_id} has an invalid envelope, admission refused: "
               f"{'; '.join(errors)}")

    if rec.get("status") != "active":
        refuse(f"run {run_id} is not active (status={rec.get('status')!r}) — admission "
               f"refused")

    actor = rec.get("actor") or {}
    if actor.get("client") != client or actor.get("session_id") != session:
        refuse(f"run {run_id} is bound to actor {actor.get('client')!r}/"
               f"{actor.get('session_id')!r}, not {client!r}/{session!r} — admission "
               f"refused")

    goal = rec.get("goal") or {}
    if goal.get("ticket") != task_id:
        refuse(f"run {run_id} is bound to ticket {goal.get('ticket')!r}, not {task_id!r} "
               f"— admission refused")

    claims = rec.get("claims") or {}
    if claims.get("scope") != scope:
        refuse(f"run {run_id}'s declared scope is {claims.get('scope')!r}, not the "
               f"caller's declared scope {scope!r} — admission requires an exact match, "
               f"never a resolved or fuzzy one")

    lease_id = claims.get("lease")
    if not lease_id:
        refuse(f"run {run_id} has no lease bound in claims.lease — admission refused")

    coord.verify_dispatch_conflict_protection(task_dir, task_id, scope, lease_id, client,
                                              session)
    return rec, lease_id


def admit_open(task_dir, task_id, run_id, scope, client, session, idem_key):
    """Fail-closed: on any admission-boundary failure, raises `CoordinationError` and
    writes nothing. On success, persists exactly one admission record for
    (client, session), guarded by `admission_guard()`, and returns it. Idempotent on a
    repeated idempotency key against a still-open record for the identical
    (task, run, scope): returns the original record unchanged, no re-verification, no
    second write. A still-open record for a *different* task/run/scope refuses outright —
    one open admission per (client, session) at a time, never silently replaced."""
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    idem_key = require_identity(idem_key, "idempotency-key")

    key = _admission_key(client, session)
    with coord.admission_guard(key):
        path = _admission_path(client, session)
        existing, corrupt = _read_json(path)
        if corrupt:
            refuse(f"admission record for {client}/{session} is corrupt — an owner must "
                   f"resolve it before a new admission can be opened")
        if existing is not None and existing.get("state") == "open":
            if existing.get("idempotency_key") == idem_key and \
               existing.get("task_id") == task_id and existing.get("run_id") == run_id and \
               existing.get("scope") == scope:
                return dict(existing, replay=True)
            refuse(f"an admission is already open for {client}/{session} (task "
                   f"{existing.get('task_id')}, run {existing.get('run_id')}) — close it "
                   f"before opening a new one")

        _, lease_id = verify_admission(task_dir, task_id, run_id, scope, client, session)

        opened_at = iso(now_utc())
        record = {
            "client_id": client, "session_id": session, "task_id": task_id,
            "run_id": run_id, "scope": scope, "lease_id": lease_id,
            "opened_at": opened_at, "state": "open", "idempotency_key": idem_key,
        }
        _atomic_write_json(path, record)
        return dict(record, replay=False)


def admit_check(client, session):
    """Read-only: is there still an open admission record on disk for (client, session).
    Does not re-run `verify_admission` against live run/lease/claim state — that
    re-verification is `admit_open`'s job; this only answers whether the admission record
    itself is still open."""
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    obj, corrupt = _read_json(_admission_path(client, session))
    if corrupt:
        refuse(f"admission record for {client}/{session} is corrupt — refused")
    if obj is None or obj.get("state") != "open":
        refuse(f"no open admission exists for {client}/{session}")
    return obj


def _resolve_task_dir(task_id):
    """Ticket id -> its task directory, via `cli/atlas-paths ticket <id>` — the one
    canonical resolver `atlas-handoff`/`atlas-coordinator` already use, never a second
    lookup implemented here. Runs as a subprocess (not an in-process import) so it inherits
    the caller's environment (including `$ATLAS_HOME`) exactly the way a shell-invoked
    resolver always has."""
    resolver = CLI_DIR / "atlas-paths"
    try:
        r = subprocess.run([str(resolver), "ticket", str(task_id)],
                           capture_output=True, text=True)
    except OSError as exc:
        refuse(f"admission refused: could not run the ticket resolver for {task_id!r} "
               f"({exc})")
    if r.returncode != 0 or not r.stdout.strip():
        refuse(f"admission refused: no task directory could be resolved for ticket "
               f"{task_id!r}")
    d = Path(r.stdout.strip())
    if not d.is_dir():
        refuse(f"admission refused: resolved task directory {d} for ticket {task_id!r} "
               f"does not exist")
    return d


def verify_write(client, session, write_path):
    """Fail-closed per-write check. Returns True on success; raises `CoordinationError` on
    the first failing condition and never continues past it:

      1. an open admission record exists on disk for exactly (client, session) — never for
         any other session, never inferred;
      2. that record's task/run/scope re-verify against live state via `verify_admission`
         (status, actor, ticket, exact scope, lease, and file claim, all checked again,
         right now — never trusted from the moment the admission was opened);
      3. `write_path` resolves to exactly the admitted scope's own canonical path.

    Never writes anything, never opens or extends an admission, never falls back to a
    different client or session."""
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    if not write_path or not str(write_path).strip():
        refuse("a write target path is required for a per-write admission check")
    write_path = str(write_path).strip()

    obj, corrupt = _read_json(_admission_path(client, session))
    if corrupt:
        refuse(f"admission record for {client}/{session} is corrupt — write refused")
    if obj is None or obj.get("state") != "open":
        refuse(f"no open admission exists for {client}/{session} — write refused")

    task_id = obj.get("task_id")
    run_id = obj.get("run_id")
    scope = obj.get("scope")
    task_dir = _resolve_task_dir(task_id)

    # Re-verify against live state; the stored record is never trusted past this point.
    verify_admission(task_dir, task_id, run_id, scope, client, session)

    scope_canonical = coord.canonicalize_path(scope)
    target_canonical = (str(Path(os.path.realpath(write_path))) if Path(write_path).is_absolute()
                        else coord.canonicalize_path(write_path))
    if target_canonical != scope_canonical:
        refuse(f"write target {write_path!r} (resolved {target_canonical}) is outside the "
               f"admitted scope {scope!r} (resolved {scope_canonical}) — write refused")
    return True


def admit_close(client, session):
    client = require_identity(client, "client")
    session = require_identity(session, "session")
    key = _admission_key(client, session)
    with coord.admission_guard(key):
        path = _admission_path(client, session)
        obj, corrupt = _read_json(path)
        if corrupt:
            refuse(f"admission record for {client}/{session} is corrupt — refused")
        if obj is None:
            refuse(f"no admission exists for {client}/{session} to close")
        if obj.get("state") == "closed":
            refuse(f"admission for {client}/{session} was already closed at "
                   f"{obj.get('closed_at')} — nothing to close")
        closed_at = iso(now_utc())
        terminal = dict(obj, state="closed", closed_at=closed_at)
        _atomic_write_json(path, terminal)
        return terminal
