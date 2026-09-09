"""atlas_client_activity — T-125: client-neutral live-activity records, gated on
successful admission. This is the observability/lifecycle layer on top of admission, never
a replacement for it: `activity_start` refuses unless handed the exact object
`atlas_admission.admit_open` returned, with `state == "open"` — it trusts nothing else the
caller claims about its own admission.

`claude-code` (`CLIENT_CLAUDE_CODE`) is exported as the first registered client id, but
nothing in the schema or the functions below special-cases it — any other client id uses
the identical calls.

One JSON record per (client_id, session_id), under
`atlas_coordination.atlas_home()/"runtime"/"coordination"/"activity"`, guarded the same
flock-based way `atlas_coordination.claim_guard`/`admission_guard` already are. Record
fields: client_id, client_name, agent_id, provider, session_id, ticket, scope, lease_id,
last_seen, expiry, status.

On-disk `status` is only ever written as "active" or "closed" — never "stale". A stale
heartbeat or an expired lease is derived fresh on every read (`activity_status`,
`list_activity`) and never written back: there is no write path an expiry check could
trigger, so "expired lease or heartbeat becomes stale, never auto-reassigned" holds by
construction. `activity_heartbeat`/`activity_close` refuse on a record that is not
currently `active` on disk — no reviving a closed record, and no reassignment path exists
in this file at all. An explicit `activity_close` still succeeds on a record whose derived
status is "stale", because closing only ever checks the on-disk `status`.
"""
import datetime
import sys
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
if str(CLI_DIR) not in sys.path:
    sys.path.insert(0, str(CLI_DIR))

import atlas_coordination as coord

CLIENT_CLAUDE_CODE = "claude-code"


def activities_dir():
    return coord.atlas_home() / "runtime" / "coordination" / "activity"


def _activity_guard(key):
    return coord._guard(activities_dir() / f".{key}.lock", "activity")


def _activity_key(client_id, session_id):
    return f"{client_id}__{session_id}"


def _activity_path(client_id, session_id):
    return activities_dir() / f"{_activity_key(client_id, session_id)}.json"


def _require_nonempty(value, label):
    if not isinstance(value, str) or not value.strip():
        coord.refuse(f"{label} is required and must be a non-empty string")
    return value.strip()


def activity_start(opened, client_name, agent_id, provider, expires_in_seconds):
    """Starts (or restarts) the live-activity record for the (client, session) that
    `opened` names. `opened` must be the exact dict `atlas_admission.admit_open` returned
    — refused unless `opened["state"] == "open"`. A second call for the same
    (client, session) with a fresh `opened` overwrites the prior record with a new
    `started_at`/`last_seen`/`expiry` — "a valid admission creates or updates activity
    status active"."""
    if not isinstance(opened, dict) or opened.get("state") != "open":
        coord.refuse("activity_start requires the exact object admit_open returned, with "
                     "state == 'open' — refusing an activity record for anything else")
    client_id = _require_nonempty(opened.get("client_id"), "opened['client_id']")
    session_id = _require_nonempty(opened.get("session_id"), "opened['session_id']")
    ticket = _require_nonempty(opened.get("task_id"), "opened['task_id']")
    scope = _require_nonempty(opened.get("scope"), "opened['scope']")
    lease_id = _require_nonempty(opened.get("lease_id"), "opened['lease_id']")
    client_name = _require_nonempty(client_name, "client_name")
    agent_id = _require_nonempty(agent_id, "agent_id")
    provider = _require_nonempty(provider, "provider")
    ttl = coord.require_ttl_seconds(expires_in_seconds)

    now = coord.now_utc()
    record = {
        "client_id": client_id, "client_name": client_name, "agent_id": agent_id,
        "provider": provider, "session_id": session_id, "ticket": ticket, "scope": scope,
        "lease_id": lease_id, "started_at": coord.iso(now), "last_seen": coord.iso(now),
        "expiry": coord.iso(now + datetime.timedelta(seconds=ttl)), "status": "active",
    }
    key = _activity_key(client_id, session_id)
    with _activity_guard(key):
        coord._atomic_write_json(_activity_path(client_id, session_id), record)
    return dict(record)


def activity_heartbeat(client_id, session_id, expires_in_seconds=None):
    client_id = _require_nonempty(client_id, "client_id")
    session_id = _require_nonempty(session_id, "session_id")
    key = _activity_key(client_id, session_id)
    with _activity_guard(key):
        path = _activity_path(client_id, session_id)
        obj, corrupt = coord._read_json(path)
        if corrupt:
            coord.refuse(f"activity record for {client_id}/{session_id} is corrupt — "
                         f"refused")
        if obj is None or obj.get("status") != "active":
            coord.refuse(f"no active activity record exists for {client_id}/{session_id} "
                         f"to heartbeat")
        now = coord.now_utc()
        updated = dict(obj, last_seen=coord.iso(now))
        if expires_in_seconds is not None:
            ttl = coord.require_ttl_seconds(expires_in_seconds)
            updated["expiry"] = coord.iso(now + datetime.timedelta(seconds=ttl))
        coord._atomic_write_json(path, updated)
        return dict(updated)


def activity_close(client_id, session_id):
    client_id = _require_nonempty(client_id, "client_id")
    session_id = _require_nonempty(session_id, "session_id")
    key = _activity_key(client_id, session_id)
    with _activity_guard(key):
        path = _activity_path(client_id, session_id)
        obj, corrupt = coord._read_json(path)
        if corrupt:
            coord.refuse(f"activity record for {client_id}/{session_id} is corrupt — "
                         f"refused")
        if obj is None:
            coord.refuse(f"no activity record exists for {client_id}/{session_id} to "
                         f"close")
        if obj.get("status") == "closed":
            coord.refuse(f"activity for {client_id}/{session_id} was already closed at "
                         f"{obj.get('closed_at')} — nothing to close")
        closed_at = coord.iso(coord.now_utc())
        terminal = dict(obj, status="closed", closed_at=closed_at)
        coord._atomic_write_json(path, terminal)
        return dict(terminal)


def _effective_status(obj, stale_seconds):
    """Never writes anything. `stale` overrides an on-disk `active` when either the
    lease/session `expiry` has passed or `last_seen` is older than `stale_seconds` — an
    expired heartbeat OR an expired lease is stale, exactly as required. `closed` is
    terminal and never overridden."""
    if obj.get("status") == "closed":
        return "closed"
    now = coord.now_utc()
    expiry = coord.parse_iso(obj.get("expiry"))
    if expiry is not None and now > expiry:
        return "stale"
    last_seen = coord.parse_iso(obj.get("last_seen"))
    if last_seen is None or (now - last_seen).total_seconds() > stale_seconds:
        return "stale"
    return "active"


def activity_status(client_id, session_id, stale_seconds=900):
    client_id = _require_nonempty(client_id, "client_id")
    session_id = _require_nonempty(session_id, "session_id")
    obj, corrupt = coord._read_json(_activity_path(client_id, session_id))
    if corrupt:
        coord.refuse(f"activity record for {client_id}/{session_id} is corrupt — refused")
    if obj is None:
        return None
    return dict(obj, status=_effective_status(obj, stale_seconds))


def list_activity(ticket, stale_seconds=900):
    """Read-only, additive listing for one ticket — every activity record whose `ticket`
    field matches, each with its `status` re-derived fresh, never mutated on disk."""
    ticket = _require_nonempty(ticket, "ticket")
    d = activities_dir()
    rows = []
    if not d.is_dir():
        return rows
    for p in sorted(d.glob("*.json")):
        obj, corrupt = coord._read_json(p)
        if corrupt or obj is None:
            continue
        if obj.get("ticket") != ticket:
            continue
        rows.append(dict(obj, status=_effective_status(obj, stale_seconds)))
    return rows
