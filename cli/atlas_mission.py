"""atlas_mission — T-051-S1: the Mission Contract and durable Mission Run State layer only.

This is a library, imported by `cli/atlas-mission`, never run directly. It writes durable
records under the existing root ticket directory (`mission/<mission-id>/contract.json`,
`mission/<mission-id>/state.json`, `mission/<mission-id>/audit.log`,
`mission/<mission-id>/idempotency/*.json`, plus a ticket-level
`mission/idempotency/*.json` for `create` replay before a mission id is known) — the same
ticket directory `atlas_tickets`/`atlas-paths` already resolve, never a second authority or a
new runtime root.

## What this slice is

A safe foundation for a later planner -> executor -> verifier loop: an owner-approved,
durable, fail-closed mission contract plus a small state machine (`created` ->
`approved`, and the reserved-but-not-yet-reachable `needs_owner` / `blocked` / `cancelled` /
`expired`). Nothing here executes anything. There is no daemon, queue, worker, scheduler,
watcher, lease, file claim, handoff, or AI invocation anywhere in this file — every function
runs once, synchronously, for the one caller that invoked it, and returns.

## Mutation guard

Every mutation (`create`, `approve`) runs inside a short-lived local `flock`-based mutation
guard on an on-disk lock file, taken with `LOCK_EX | LOCK_NB` in a short bounded poll loop and
released in a `finally` — the same technique `cli/atlas_coordination.py` uses (S6-R1), kept as
an independent, self-contained copy here rather than importing that module's private helpers,
so a future change to the coordination file cannot silently change mission-contract behavior,
and vice versa. Two guard scopes exist: a ticket-level guard (`mission/.mutation.lock`) used by
`create`, for allocating/uniqueness-checking a mission id before it exists; and a mission-level
guard (`mission/<mission-id>/.mutation.lock`) used by `approve`, for the one legitimate mutator
of an existing mission's state. If a guard cannot be acquired within the bounded wait, the
whole operation refuses (fails closed) rather than blocking or proceeding unserialized.

## Two files, two lifetimes

`contract.json` is written exactly once, at `create`, and never rewritten: the declared,
owner-reviewable terms of the mission (scope, roles, tools, limits, policy text). `state.json`
is the durable *run state*: `state`, `approval`, and (once recorded) the approval evidence.
`create` writes both (state: `created`, approval: `none`); `approve` rewrites only
`state.json`, validating that the current state is exactly `created` before doing so.

Zero non-stdlib dependencies.
"""
import contextlib
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
import datetime
from pathlib import Path

CLI_DIR = Path(__file__).resolve().parent
PATHS_RESOLVER = CLI_DIR / "atlas-paths"


def adapters_dir():
    """Read at call time, never cached at import — the same posture as `atlas_home()` below,
    and required for `ATLAS_ADAPTERS` to be honored by a caller (a test fixture) that sets it
    after this module has already been imported."""
    return Path(os.environ.get("ATLAS_ADAPTERS", CLI_DIR.parent / "adapters"))

# One identifier shape for every bare token this file accepts (mission id, idempotency key,
# planner/executor/verifier client id): [A-Za-z0-9][A-Za-z0-9._-]{0,63}. Kept as its own
# regex object (not imported from cli/atlas_coordination.py) for the same independence reason
# given in the module docstring.
IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
PATH_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/\-]*\Z")

# S1's own declared set, kept exactly as S1-S5 defined it — deliberately NOT extended here.
# Prior slices' own tests assert facts about this exact tuple (e.g. "'completed' is not a
# declared state" was true through S5), and this file's established convention (see every
# "independent copy" note above) is to never retroactively change a fact an earlier, frozen
# slice already tested. `completed`/`failed` are real, reachable values as of T-051-S6 —
# task.md's own mission-states diagram already named them — but they are declared in
# `VALID_STATE_VALUES` below, a strict superset `load_mission` actually validates against,
# so `MISSION_STATES` itself stays byte-for-byte what it always was.
MISSION_STATES = ("created", "approved", "needs_owner", "blocked", "cancelled", "expired")
APPROVAL_STATES = ("none", "recorded")

# T-051-S6: the superset `load_mission` validates a persisted `state.json` value against.
# `mission finalize` is the only command that ever writes `completed` or `failed`.
VALID_STATE_VALUES = MISSION_STATES + ("completed", "failed")

# T-051-S6: a mission in any of these states is closed — no further handoff, continuation,
# or finalize may act on it (finalize's own idempotent replay is the one narrow exception,
# and it is keyed to the exact original request, never a fresh one).
TERMINAL_STATES = ("completed", "blocked", "failed", "needs_owner", "cancelled", "expired")

# T-051-S2: the three roles this slice routes. A generic role model — the client behind a
# role is whatever the approved contract names, never a hard-coded vendor preference.
ROLE_CONTRACT_FIELD = {"planner": "planner_client", "executor": "executor_client",
                       "verifier": "verifier_client"}
ROLES = tuple(ROLE_CONTRACT_FIELD)

# S1's own reachable transition, plus the four terminal transitions T-051-S6 adds:
# `mission finalize` is the only command that ever writes one of these four, and only after
# reading a persisted, non-self-reported verifier classification (see `mission_finalize`).
# Fail closed: anything not literally one of these five pairs is refused.
ALLOWED_TRANSITIONS = {
    ("created", "approved"),
    ("approved", "completed"),
    ("approved", "blocked"),
    ("approved", "failed"),
    ("approved", "needs_owner"),
}

DEFAULT_ALLOWED_TOOLS = ["Read", "Edit"]
DEFAULT_DENIED_TOOLS = ["Bash", "network", "MCP", "Git", "delete", "publish", "credentials"]

# Section G of the S1 prompt, verbatim, as a durable declared field on every mission
# contract — never executed, never checked against at runtime in this slice (there is no
# runtime loop yet), just recorded so a later slice's loop has one shared list to enforce.
FORBIDDEN_ACTIONS = [
    "ai_invocation", "handoff_prepare", "handoff_approve", "handoff_send", "handoff_receive",
    "coordinator_dispatch", "lease_acquisition", "file_claims", "background_process",
    "daemon", "queue", "worker", "scheduler", "watcher", "network", "mcp", "bash_shell_out",
    "git_command", "publication", "deletion", "credential_access", "permission_change",
]

STOP_CONDITIONS = [
    "budget_usd would be exceeded",
    "max_slices reached",
    "max_attempts reached",
    "ttl_seconds elapsed",
    "evidence is missing, ambiguous, or contradictory",
    "an action would fall outside the declared scope",
    "an action requires a tool not in allowed_tools, or any tool in denied_tools",
    "identity of planner/executor/verifier does not match the approved contract",
]

ROLLBACK_POLICY = (
    "Disable the Mission Loop entry point and return to the existing manual coordinator "
    "flow. Preserve mission records and audit evidence. Never delete executor files or "
    "rewrite existing V6 handoff records during rollback."
)

REQUIRED_VERIFICATION_POLICY = {
    "enforced_in_this_slice": False,
    "description": (
        "T-051-S1 declares the verifier role and identity only. No planner, executor, or "
        "verifier step executes in this slice, so no verification command runs yet — "
        "verification enforcement is later-slice work (T-051-S4)."
    ),
}

# Credential shapes this file refuses in any text field it accepts (mission id, scopes,
# client identities, idempotency key, owner words). Kept as an independent copy of the same
# narrow family `cli/atlas-handoff` already scans for — not imported from that protected
# file, for the same independence reason given in the module docstring.
CREDENTIAL = [
    ("private key block", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |PGP |DSA )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("connection string with password", re.compile(
        r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:@/]+:[^\s:@/]+@")),
    ("assigned secret literal", re.compile(
        r"(?i)\b(?:api[_\-]?key|secret[_\-]?key|access[_\-]?token|auth[_\-]?token"
        r"|client[_\-]?secret|password|passwd)\b\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']")),
]


class MissionError(Exception):
    """One refusal, with the exit code the CLI layer should use. Never raised for anything
    that succeeded partially — every function in this file either completes one operation
    fully (one atomic write per file) or raises before writing anything."""
    def __init__(self, message, code=2):
        super().__init__(message)
        self.code = code


def refuse(message, code=2):
    raise MissionError(message, code)


# --- time ---------------------------------------------------------------------------------
def now_utc():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).isoformat()


# --- home / storage roots -------------------------------------------------------------------
def atlas_home():
    v = os.environ.get("ATLAS_HOME")
    return Path(v) if v else Path.home() / "atlas"


def mission_root_dir(task_dir):
    """Per-ticket mission container. Lives under the existing ticket directory — never a
    second, parallel store, and never a new runtime root."""
    return Path(task_dir) / "mission"


def mission_dir(task_dir, mission_id):
    return mission_root_dir(task_dir) / mission_id


def contract_path(task_dir, mission_id):
    return mission_dir(task_dir, mission_id) / "contract.json"


def state_path(task_dir, mission_id):
    return mission_dir(task_dir, mission_id) / "state.json"


def audit_path(task_dir, mission_id):
    return mission_dir(task_dir, mission_id) / "audit.log"


# --- mutation guard ---------------------------------------------------------------------
_GUARD_TIMEOUT_SECONDS = 5.0
_GUARD_POLL_SECONDS = 0.02


@contextlib.contextmanager
def _guard(lock_path, label):
    """A short-lived, local, `flock`-based mutual-exclusion guard — never a daemon, queue,
    worker or scheduler. See the module docstring for the fixed-scope rationale. Fails
    closed if the guard cannot be acquired within the bounded wait."""
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
                   f"read/validate/write", code=5)
        yield
    finally:
        if acquired:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def ticket_guard(task_dir):
    return _guard(mission_root_dir(task_dir) / ".mutation.lock", "mission-ticket")


def mission_guard(task_dir, mission_id):
    return _guard(mission_dir(task_dir, mission_id) / ".mutation.lock", "mission")


# --- low-level atomic file helpers -------------------------------------------------------
def _atomic_write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.tmp{os.getpid()}"
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True))
    os.replace(tmp, path)


def _read_json(path):
    """(obj, corrupt) — obj is None and corrupt is False when the file simply does not
    exist; obj is None and corrupt is True when it exists but fails to parse, which callers
    treat as a fail-closed refusal, never a guess."""
    if not path.is_file():
        return None, False
    try:
        obj = json.loads(path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None, True
    if not isinstance(obj, dict):
        return None, True
    return obj, False


def audit_append(task_dir, mission_id, event):
    """Append-only. One JSON line per create/approve event, never overwritten, never
    truncated, never rewritten in place."""
    p = audit_path(task_dir, mission_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("at", iso(now_utc()))
    with open(p, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


# --- idempotency ---------------------------------------------------------------------
def _idempotency_path(root, key):
    return root / "idempotency" / f"{key}.json"


def idempotency_check(root, key, op, target):
    """None if this key has not been seen. The cached result dict if the same
    (op, target, key) was already performed — returned again, unchanged, no second side
    effect. A refusal if the same key was already used for a *different* operation/target."""
    p = _idempotency_path(root, key)
    obj, corrupt = _read_json(p)
    if obj is None:
        if corrupt:
            refuse(f"idempotency record for key {key!r} is corrupt — refusing rather than "
                   f"guessing whether this is a duplicate request", code=5)
        return None
    if obj.get("op") != op or obj.get("target") != target:
        refuse(f"idempotency key {key!r} was already used for a different operation/target "
               f"({obj.get('op')!r}/{obj.get('target')!r}) — refusing an ambiguous replay",
               code=5)
    return obj.get("result")


def idempotency_store(root, key, op, target, result):
    p = _idempotency_path(root, key)
    _atomic_write_json(p, {"op": op, "target": target, "result": result,
                           "stored_at": iso(now_utc())})


# --- credential scanning -------------------------------------------------------------------
def scan_credentials(*texts):
    for text in texts:
        for label, rx in CREDENTIAL:
            if rx.search(text or ""):
                refuse(f"a supplied value carries a {label}. Nothing was written. A mission "
                       f"record is durable — use key names only, never values.", code=2)


# --- identity / value validation -------------------------------------------------------
def require_identity(value, label):
    if value is None or not str(value).strip():
        refuse(f"--{label} is required")
    value = str(value).strip()
    if not IDENTITY.fullmatch(value):
        refuse(f"not a valid {label}: {value!r} — one token of [A-Za-z0-9._-]")
    scan_credentials(value)
    return value


def require_positive_int(value, label):
    if value is None or not str(value).strip():
        refuse(f"--{label} is required")
    try:
        n = int(str(value).strip())
    except ValueError:
        refuse(f"--{label} must be a positive integer, not {value!r}")
    if n <= 0:
        refuse(f"--{label} must be a positive integer, not {value!r}")
    return n


def require_budget_usd(value):
    if value is None or not str(value).strip():
        refuse("--budget-usd is required")
    try:
        n = float(str(value).strip())
    except ValueError:
        refuse(f"--budget-usd must be a finite non-negative number, not {value!r}")
    if not math.isfinite(n):
        refuse(f"--budget-usd must be a finite non-negative number, not {value!r}")
    if n < 0:
        refuse(f"--budget-usd must be non-negative, not {value!r}")
    return n


def require_text(value, label):
    if value is None or not str(value).strip():
        refuse(f"--{label} is required and must be non-empty")
    value = str(value).strip()
    scan_credentials(value)
    return value


# --- client registry (informational only — never invents a capability or a verified claim)
def known_clients():
    """The adapter registry's own declared client ids, read-only. A planner/executor/verifier
    identity absent from this list is not refused in this slice (this file does not invent
    routing or capability decisions) — it is only ever reported as `registered: false` on the
    contract, so a later slice can decide what that means without this one having guessed."""
    d = adapters_dir()
    if not d.is_dir():
        return []
    return sorted(x.name for x in d.iterdir()
                  if d.is_dir() and (d / "adapter.yaml").is_file())


# --- root ticket resolution ----------------------------------------------------------------
def resolve_task_dir(task_id):
    """The absolute directory holding the root ticket's record, via the one existing
    resolver every other command already uses (`atlas-paths ticket <id>`) — read-only,
    never creates, moves, or deletes anything."""
    if not task_id or not IDENTITY.fullmatch(str(task_id).strip()):
        refuse(f"not a ticket id: {task_id!r} — one token of [A-Za-z0-9._-]")
    task_id = str(task_id).strip()
    if not PATHS_RESOLVER.exists():
        refuse(f"broken install: {PATHS_RESOLVER} is missing", code=5)
    r = subprocess.run([str(PATHS_RESOLVER), "ticket", task_id],
                       capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        for line in r.stderr.splitlines():
            print(line, file=sys.stderr)
        refuse(f"no ticket {task_id} — a mission is bound to a root ticket that already "
               f"exists", code=4)
    d = Path(r.stdout.strip())
    if not d.is_dir():
        refuse(f"no ticket directory at {d} — a mission is bound to a root ticket that "
               f"already exists", code=4)
    return d


def task_field(task_dir, key, default="-"):
    """One frontmatter value from the root ticket's own record, read-only."""
    f = Path(task_dir) / "task.md"
    if not f.is_file():
        return default
    try:
        text = f.read_text(errors="replace")
    except OSError:
        return default
    if not text.startswith("---") or text.count("---") < 2:
        return default
    head = text.split("---", 2)[1]
    for line in head.splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() == key and v.strip():
            return v.strip()
    return default


# --- scope canonicalization ------------------------------------------------------------
def canonicalize_scope(raw_path):
    """Every scope safety rule from the S1 prompt in one place: no absolute path, no
    traversal, no shell metacharacters, no directory scope, must resolve under the allowed
    Atlas root. Identical rule set to `cli/atlas_coordination.canonicalize_path`, kept as an
    independent copy for the module-docstring's independence reason."""
    if raw_path is None or not str(raw_path).strip():
        refuse("--scope is required and must be non-empty")
    raw_path = str(raw_path).strip()
    scan_credentials(raw_path)
    if raw_path.startswith("/") or raw_path.startswith("~"):
        refuse(f"--scope {raw_path!r} is an absolute path — a mission scope must be "
               f"relative to the Atlas workspace root")
    if any(part == ".." for part in raw_path.split("/")):
        refuse(f"--scope {raw_path!r} contains '..' — traversal is refused")
    if not PATH_SAFE.fullmatch(raw_path):
        refuse(f"--scope {raw_path!r} is not a safe relative path — [A-Za-z0-9._/-] only, "
               f"no shell characters, no empty segments")
    home = atlas_home()
    home_real = Path(os.path.realpath(str(home)))
    candidate = home / raw_path
    real = Path(os.path.realpath(str(candidate)))
    try:
        real.relative_to(home_real)
    except ValueError:
        refuse(f"--scope {raw_path!r} resolves to {real}, outside the allowed Atlas root "
               f"{home_real} — refused before it reaches mission logic")
    if real.is_dir():
        refuse(f"--scope {raw_path!r} is a directory — mission scopes are always "
               f"file-scoped, never directory-scoped")
    return {"raw": raw_path, "canonical": str(real)}


def canonicalize_scopes(raw_paths):
    if not raw_paths:
        refuse("at least one --scope is required")
    scopes = [canonicalize_scope(p) for p in raw_paths]
    seen = set()
    for s in scopes:
        if s["canonical"] in seen:
            refuse(f"duplicate scope after canonicalization: {s['canonical']} "
                   f"(from {s['raw']!r})")
        seen.add(s["canonical"])
    return scopes


# --- mission id ---------------------------------------------------------------------------
def validate_mission_id(value):
    if value is None or not str(value).strip():
        return None
    value = str(value).strip()
    if not IDENTITY.fullmatch(value):
        refuse(f"not a valid --mission-id: {value!r} — one token of [A-Za-z0-9._-]")
    scan_credentials(value)
    return value


def gen_mission_id():
    return "mission-" + uuid.uuid4().hex


# --- create ---------------------------------------------------------------------------------
def mission_create(task_dir, root_task_id, project, scopes_raw, planner, executor, verifier,
                    budget_usd, max_slices, max_attempts, ttl_seconds, idempotency_key,
                    mission_id=None, source_session_id=None):
    """Validate everything before writing anything (section B of the S1 prompt), then write
    an unapproved mission: `contract.json` (immutable) and `state.json`
    (`state: created`, `approval: none`). No lease, no claim, no handoff, no AI invocation."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    explicit_mission_id = validate_mission_id(mission_id)
    scopes = canonicalize_scopes(scopes_raw)
    planner = require_identity(planner, "planner")
    executor = require_identity(executor, "executor")
    verifier = require_identity(verifier, "verifier")
    budget_usd = require_budget_usd(budget_usd)
    max_slices = require_positive_int(max_slices, "max-slices")
    max_attempts = require_positive_int(max_attempts, "max-attempts")
    ttl_seconds = require_positive_int(ttl_seconds, "ttl-seconds")
    if source_session_id is not None:
        source_session_id = require_identity(source_session_id, "source-session-id")

    root = mission_root_dir(task_dir)
    with ticket_guard(task_dir):
        cached = idempotency_check(root, idempotency_key, "mission_create", root_task_id)
        if cached is not None:
            return dict(cached, replay=True)

        if explicit_mission_id is not None:
            mid = explicit_mission_id
            if mission_dir(task_dir, mid).is_dir():
                refuse(f"mission id {mid!r} already exists for ticket {root_task_id} — a "
                       f"fresh idempotency key cannot reuse an existing mission id", code=5)
        else:
            mid = gen_mission_id()
            while mission_dir(task_dir, mid).is_dir():
                mid = gen_mission_id()

        clients_known = known_clients()
        created_at = iso(now_utc())
        created_by = (os.environ.get("USER") or os.environ.get("LOGNAME")
                      or "unknown").strip() or "unknown"

        contract = {
            "mission_id": mid,
            "root_task_id": root_task_id,
            "project": project,
            "created_at": created_at,
            "created_by": created_by,
            "planner_client": planner,
            "planner_client_registered": planner in clients_known,
            "executor_client": executor,
            "executor_client_registered": executor in clients_known,
            "verifier_client": verifier,
            "verifier_client_registered": verifier in clients_known,
            "scopes": scopes,
            "allowed_tools": list(DEFAULT_ALLOWED_TOOLS),
            "denied_tools": list(DEFAULT_DENIED_TOOLS),
            "budget_usd": budget_usd,
            "max_slices": max_slices,
            "max_attempts": max_attempts,
            "ttl_seconds": ttl_seconds,
            "required_verification_policy": dict(REQUIRED_VERIFICATION_POLICY),
            "forbidden_actions": list(FORBIDDEN_ACTIONS),
            "stop_conditions": list(STOP_CONDITIONS),
            "rollback_policy": ROLLBACK_POLICY,
            "audit_reference": str(audit_path(task_dir, mid)),
            "idempotency_reference": str(_idempotency_path(root, idempotency_key)),
            "no_autonomous_approval": True,
            "no_autonomous_publication": True,
            "no_autonomous_deletion": True,
            "no_autonomous_permission_changes": True,
            "no_automatic_recovery": True,
            "no_background_execution": True,
        }
        if source_session_id is not None:
            contract["source_session_id"] = source_session_id

        state = {
            "mission_id": mid,
            "state": "created",
            "approval": "none",
            "approved_at": None,
            "owner_words": None,
            "approval_scope_hash": None,
            "updated_at": created_at,
        }

        _atomic_write_json(contract_path(task_dir, mid), contract)
        _atomic_write_json(state_path(task_dir, mid), state)
        audit_append(task_dir, mid, {"op": "mission_create", "mission_id": mid,
                                     "root_task_id": root_task_id, "created_by": created_by})

        result = {"mission_id": mid, "root_task_id": root_task_id, "state": "created",
                  "approval": "none", "created_at": created_at}
        idempotency_store(root, idempotency_key, "mission_create", root_task_id, result)
        return dict(result, replay=False)


# --- approve ----------------------------------------------------------------------------
def _scope_hash(contract):
    canon = sorted(s["canonical"] for s in contract.get("scopes", []))
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode()).hexdigest()


def load_mission(task_dir, mission_id):
    if not IDENTITY.fullmatch(str(mission_id or "")):
        refuse(f"not a mission id: {mission_id!r}")
    d = mission_dir(task_dir, mission_id)
    if not d.is_dir():
        refuse(f"no mission {mission_id!r} for this ticket", code=4)
    contract, corrupt = _read_json(contract_path(task_dir, mission_id))
    if contract is None:
        refuse(f"mission {mission_id!r} has no readable contract.json"
               + (" (corrupt)" if corrupt else " (missing)"), code=5)
    state, corrupt = _read_json(state_path(task_dir, mission_id))
    if state is None:
        refuse(f"mission {mission_id!r} has no readable state.json"
               + (" (corrupt)" if corrupt else " (missing)"), code=5)
    if state.get("state") not in VALID_STATE_VALUES:
        refuse(f"mission {mission_id!r} has an invalid state {state.get('state')!r} — "
               f"refusing rather than guessing", code=5)
    if state.get("approval") not in APPROVAL_STATES:
        refuse(f"mission {mission_id!r} has an invalid approval value "
               f"{state.get('approval')!r} — refusing rather than guessing", code=5)
    return contract, state


def mission_approve(task_dir, root_task_id, mission_id, owner_words, idempotency_key):
    """Requires explicit non-empty owner words. Requires the mission to be in state
    `created`. Records approval evidence exactly once, immutably: a second call with the
    same idempotency key replays the original result; any other call once approved is
    refused."""
    owner_words = require_text(owner_words, "owner-words")
    idempotency_key = require_identity(idempotency_key, "idempotency-key")

    contract, _ = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}")

    with mission_guard(task_dir, mission_id):
        idem_root = mission_dir(task_dir, mission_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_approve", mission_id)
        if cached is not None:
            return dict(cached, replay=True)

        contract, state = load_mission(task_dir, mission_id)
        current = state.get("state")
        if (current, "approved") not in ALLOWED_TRANSITIONS:
            if current == "approved":
                refuse(f"mission {mission_id!r} is already approved — a different approval "
                       f"attempt after approval is refused; the recorded approval is "
                       f"immutable", code=5)
            refuse(f"mission {mission_id!r} is in state {current!r} — approval is only "
                   f"valid from state 'created'", code=5)

        approved_at = iso(now_utc())
        new_state = dict(state)
        new_state.update({
            "state": "approved",
            "approval": "recorded",
            "approved_at": approved_at,
            "owner_words": owner_words,
            "approval_scope_hash": _scope_hash(contract),
            "updated_at": approved_at,
        })
        _atomic_write_json(state_path(task_dir, mission_id), new_state)
        audit_append(task_dir, mission_id, {"op": "mission_approve", "mission_id": mission_id,
                                            "root_task_id": root_task_id,
                                            "approved_at": approved_at})

        result = {"mission_id": mission_id, "root_task_id": root_task_id,
                  "state": "approved", "approval": "recorded", "approved_at": approved_at,
                  "approval_scope_hash": new_state["approval_scope_hash"]}
        idempotency_store(idem_root, idempotency_key, "mission_approve", mission_id, result)
        return dict(result, replay=False)


# --- read-only view (show / status) ---------------------------------------------------------
NEXT_OWNER_ACTION = {
    "created": ("approve the mission contract (`mission approve <root-task-id> "
                "<mission-id> --owner-words \"...\" --idempotency-key <key>`), or leave it "
                "unapproved — no executor action exists in this slice either way"),
    "approved": ("a bounded planner-to-executor handoff may be created via `mission "
                 "handoff` (T-051-S3); no continuation loop exists — each handoff is a "
                 "single, owner-triggered, foreground call, never automatic"),
    "completed": ("mission finalized as completed (T-051-S6) — see this mission's own "
                  "`mission/<mission-id>/final/final-report.json`; nothing further is "
                  "automatic"),
    "blocked": ("mission finalized as blocked (T-051-S6) — see this mission's own "
                "`mission/<mission-id>/final/blocker-packet.json`; owner review required"),
    "failed": ("mission finalized as failed (T-051-S6) — see this mission's own "
              "`mission/<mission-id>/final/blocker-packet.json`; owner review required"),
    "needs_owner": ("mission finalized as needs_owner (T-051-S6) — see this mission's own "
                    "`mission/<mission-id>/final/owner-decision-packet.json`; an explicit "
                    "owner decision is required"),
}


def mission_view(task_dir, mission_id):
    """Read-only: contract + state, merged into one deterministic view. Never changes
    state, never approves, never calls any AI, never acquires a lease or a claim."""
    contract, state = load_mission(task_dir, mission_id)
    view = {
        "mission_id": contract["mission_id"],
        "root_task_id": contract["root_task_id"],
        "project": contract.get("project"),
        "state": state.get("state"),
        "approval": state.get("approval"),
        "created_at": contract.get("created_at"),
        "created_by": contract.get("created_by"),
        "approved_at": state.get("approved_at"),
        "owner_words": state.get("owner_words"),
        "approval_scope_hash": state.get("approval_scope_hash"),
        "planner_client": contract.get("planner_client"),
        "planner_client_registered": contract.get("planner_client_registered"),
        "executor_client": contract.get("executor_client"),
        "executor_client_registered": contract.get("executor_client_registered"),
        "verifier_client": contract.get("verifier_client"),
        "verifier_client_registered": contract.get("verifier_client_registered"),
        "source_session_id": contract.get("source_session_id"),
        "scopes": contract.get("scopes", []),
        "allowed_tools": contract.get("allowed_tools", []),
        "denied_tools": contract.get("denied_tools", []),
        "budget_usd": contract.get("budget_usd"),
        "max_slices": contract.get("max_slices"),
        "max_attempts": contract.get("max_attempts"),
        "ttl_seconds": contract.get("ttl_seconds"),
        "required_verification_policy": contract.get("required_verification_policy"),
        "forbidden_actions": contract.get("forbidden_actions", []),
        "stop_conditions": contract.get("stop_conditions", []),
        "rollback_policy": contract.get("rollback_policy"),
        "audit_reference": contract.get("audit_reference"),
        "idempotency_reference": contract.get("idempotency_reference"),
        "attempts_used": state.get("attempts_used", 0),
        "budget_committed_usd": state.get("budget_committed_usd", 0.0),
        "last_handoff_id": state.get("last_handoff_id"),
        "handoffs": state.get("handoffs", []),
        "next_owner_action": NEXT_OWNER_ACTION.get(
            state.get("state"),
            "no action defined for this state in T-051-S1 — this state is reserved, not "
            "yet reachable in this slice"),
        "execution_enabled_in_this_slice": False,
    }
    return view


# ============================================================================================
# T-051-S2 — generic role and capability resolution.
#
# `mission route` and `mission validate` are both entirely read-only: they load the existing
# mission contract, resolve its declared planner/executor/verifier client against the two
# existing registries (`adapters/*/adapter.yaml`, `governance/policies/
# handoff-transports.yaml`), and report what would be used — never invoking a client,
# acquiring a lease or claim, preparing a handoff, or writing anything. No new registry is
# introduced; both existing ones are read with the same manifest parser and the same
# resolver function (`atlas-handoff.resolve_transport`) the coordinator already uses.
# ============================================================================================

def _load_sibling(name):
    """Load a sibling CLI file as a library module, never as `__main__` — the identical
    technique `cli/atlas-coordinator._load_sibling` already uses to reuse `cli/atlas-adapter`
    and `cli/atlas-handoff` without forking a second copy of either. Kept as an independent
    copy in this file for the same reason every other helper here is independent: a change to
    the coordinator's loader must never silently change mission routing, and vice versa."""
    src = CLI_DIR / name
    if not src.exists():
        refuse(f"cli/{name} is missing; mission routing reuses it and cannot run without it",
               code=5)
    mod_name = "_atlas_mission_" + name.replace("-", "_").replace(".", "_")
    spec = importlib.util.spec_from_loader(
        mod_name, importlib.machinery.SourceFileLoader(mod_name, str(src)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_adapter(client):
    """(manifest_dict, None) or (None, reason) — read-only. `client` must already be
    IDENTITY-shaped; this only ever looks for a directory of that exact name under
    `adapters/`. No alias, prefix, or binary-name lookup is attempted: an adapter absent
    under the client's own declared name is reported missing, never guessed at."""
    manifest_path = adapters_dir() / client / "adapter.yaml"
    if not manifest_path.is_file():
        return None, f"no adapter is registered for client {client!r} at {manifest_path}"
    adapter_mod = _load_sibling("atlas-adapter")
    try:
        doc = adapter_mod.parse(manifest_path.read_text(errors="replace"), str(manifest_path))
    except adapter_mod.ManifestError as e:
        return None, f"adapter manifest for {client!r} will not parse: {e}"
    if not isinstance(doc, dict):
        return None, f"adapter manifest for {client!r} is malformed: expected a mapping"
    return doc, None


def adapter_capabilities(adapter_doc):
    """The adapter's own declared, verified `provides` keys — this registry's own capability
    vocabulary (e.g. `rules`, `skills`, `hooks`, `mcp`), never translated into a different
    namespace and never invented. A `provides` entry not marked `verified: true` is not a
    capability, exactly as the adapter manifest's own comments say documentation is not
    evidence."""
    provides = adapter_doc.get("provides") if isinstance(adapter_doc, dict) else None
    if not isinstance(provides, dict):
        return []
    return sorted(k for k, v in provides.items()
                  if isinstance(v, dict) and v.get("verified") is True)


def transport_tool_capabilities(transport_spec):
    """Explicit only: the transport's own `--tools` argv value, split on commas, exactly as
    it appears. Never derived from the binary name, the client id, or any other field — a
    transport with no `--tools` flag at all declares zero tool capabilities, not an unknown
    or unlimited set."""
    argv = transport_spec.get("argv") if isinstance(transport_spec, dict) else None
    if not isinstance(argv, list):
        return []
    for i, a in enumerate(argv):
        if a == "--tools" and i + 1 < len(argv):
            val = argv[i + 1]
            if not isinstance(val, str) or not val.strip():
                return []
            return sorted(tok.strip() for tok in val.split(",") if tok.strip())
    return []


def _adapter_transport_identity_conflict(client, adapter_doc, transport_spec):
    """A narrow, evidence-based contradiction check between the two existing registries —
    never a guess from the client name. If the adapter declares a `version_cmd` (its own
    stated way to identify its binary) and the transport declares a `binary`, for the SAME
    client id, and the two name different binaries, that is a real contradiction between two
    registries both claiming to describe the same client. Returns a reason string, or None
    if there is nothing to compare or nothing contradictory."""
    if not isinstance(adapter_doc, dict) or not isinstance(transport_spec, dict):
        return None
    client_block = adapter_doc.get("client")
    if not isinstance(client_block, dict):
        return None
    version_cmd = client_block.get("version_cmd")
    if not isinstance(version_cmd, str) or not version_cmd.strip():
        return None
    adapter_binary = version_cmd.strip().split()[0]
    transport_binary = transport_spec.get("binary")
    if not isinstance(transport_binary, str) or not transport_binary:
        return None
    if adapter_binary != transport_binary:
        return (f"adapter {client!r} declares binary {adapter_binary!r} (via its "
                f"version_cmd), but the transport registered for {client!r} declares binary "
                f"{transport_binary!r} — contradictory identity between the two existing "
                f"registries, refusing rather than guessing which one is right")
    return None


def _resolve_role_client(contract, role):
    if role not in ROLES:
        refuse(f"not a role: {role!r} — one of {', '.join(ROLES)}", code=2)
    field = ROLE_CONTRACT_FIELD[role]
    client = contract.get(field)
    if not client or not IDENTITY.fullmatch(str(client)):
        refuse(f"mission {contract.get('mission_id')!r} has no valid {role} client declared "
               f"({field} = {client!r})", code=5)
    return str(client)


def resolve_role(task_dir, root_task_id, mission_id, role):
    """The read-only resolution shared by `route` and `validate`: load the approved mission,
    resolve one role's client against the adapter registry and the transport registry, check
    the two are not contradictory, and return everything a caller needs to report — a
    capability decision is layered on top by `mission_route`, since `validate` calls this
    once per role with no capability requested."""
    contract, state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)
    if state.get("state") != "approved" or state.get("approval") != "recorded":
        refuse(f"mission {mission_id!r} is in state {state.get('state')!r} / approval "
               f"{state.get('approval')!r} — routing requires an approved mission", code=5)

    client = _resolve_role_client(contract, role)

    hoff = _load_sibling("atlas-handoff")
    transport_spec, binary, unavailable = hoff.resolve_transport(client)
    if transport_spec is None:
        refuse(f"no transport is declared for client {client!r} in "
               f"{hoff.TRANSPORTS} — refusing rather than guessing one", code=4)
    transport_verified = transport_spec.get("verified") is True

    adapter_doc, adapter_err = load_adapter(client)
    if adapter_doc is None:
        refuse(f"adapter missing for client {client!r}: {adapter_err}", code=4)

    if not transport_verified:
        refuse(f"the {client!r} transport is declared but not verified "
               f"({unavailable}) — refusing", code=5)

    conflict = _adapter_transport_identity_conflict(client, adapter_doc, transport_spec)
    if conflict:
        refuse(conflict, code=5)

    return {
        "contract": contract,
        "state": state,
        "role": role,
        "client": client,
        "adapter_id": adapter_doc.get("adapter", client),
        "transport_id": client,
        "transport_verified": transport_verified,
        "adapter_capabilities": adapter_capabilities(adapter_doc),
        "transport_tool_capabilities": transport_tool_capabilities(transport_spec),
        "mission_allowed_tools": list(contract.get("allowed_tools", [])),
        "mission_denied_tools": list(contract.get("denied_tools", [])),
    }


def mission_route(task_dir, root_task_id, mission_id, role, capability=None):
    """Read-only. No mission state change, no lease, no file claim, no handoff, no approval,
    no send, no dispatch, no AI invocation, no next task creation — every one of those would
    be a write or a subprocess call to a client binary, and this function does neither."""
    resolved = resolve_role(task_dir, root_task_id, mission_id, role)
    allowed = resolved["mission_allowed_tools"]
    denied = resolved["mission_denied_tools"]
    transport_caps = resolved["transport_tool_capabilities"]
    client = resolved["client"]

    capability_decision = "not_requested"
    if capability is not None:
        capability = str(capability).strip()
        if not capability:
            refuse("--capability was given but is empty", code=2)
        if capability in denied:
            refuse(f"capability {capability!r} is in the mission's own denied_tools "
                   f"{denied} — refusing", code=5)
        if capability not in allowed:
            refuse(f"capability {capability!r} is not within the mission's allowed_tools "
                   f"{allowed} — capability_unavailable, refusing rather than exceeding the "
                   f"mission boundary", code=5)
        if capability not in transport_caps:
            refuse(f"capability {capability!r} is not declared by the {client!r} "
                   f"transport's own --tools flag ({transport_caps or 'none declared'}) — "
                   f"capability_unavailable, a verified transport is not permission to "
                   f"exceed what it itself declares", code=5)
        capability_decision = "capability_available"

    return {
        "mission_id": mission_id,
        "root_task_id": root_task_id,
        "role": role,
        "client": client,
        "adapter_id": resolved["adapter_id"],
        "transport_id": resolved["transport_id"],
        "transport_verified": resolved["transport_verified"],
        "adapter_capabilities": resolved["adapter_capabilities"],
        "transport_tool_capabilities": transport_caps,
        "mission_allowed_tools": allowed,
        "requested_capability": capability,
        "capability_decision": capability_decision,
        "next_action": (
            "read-only: no client was invoked by this command. Use the existing "
            "coordinator prepare/dispatch flow (owner-approved, per T-050) to actually hand "
            "work to this client — no Mission Loop continuation exists yet."),
    }


def _parse_json_object(text, label):
    """Accept one JSON object, optionally wrapped in one markdown json fence."""
    text = (text or "").strip()
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() in ("```", "```json") and lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as e:
        refuse(f"{label} did not return one JSON object: {e}", code=5)
    if not isinstance(value, dict):
        refuse(f"{label} did not return a JSON object", code=5)
    return value


def _validate_plan(contract, plan):
    scopes = {s.get("raw") for s in contract.get("scopes", [])}
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        refuse("planner returned no steps", code=5)
    max_slices = contract.get("max_slices")
    if len(steps) > max_slices:
        refuse(f"planner returned {len(steps)} steps, above max_slices {max_slices}", code=5)
    clean = []
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            refuse(f"planner step {index} is not an object", code=5)
        scope = step.get("scope")
        objective = step.get("objective")
        if scope not in scopes:
            refuse(f"planner step {index} selected unapproved scope {scope!r}", code=5)
        if not isinstance(objective, str) or not objective.strip():
            refuse(f"planner step {index} has no objective", code=5)
        clean.append({"scope": scope, "objective": objective.strip()})
    return {
        "summary": str(plan.get("summary") or "").strip(),
        "steps": clean,
        "tests": plan.get("tests") if isinstance(plan.get("tests"), list) else [],
    }


def mission_plan(task_dir, root_task_id, mission_id, planner_session, invocation_id,
                 idempotency_key):
    """Run exactly one verified read-only planner call and persist its bounded plan."""
    for value, label in ((planner_session, "planner-session"),
                         (invocation_id, "invocation-id"),
                         (idempotency_key, "idempotency-key")):
        require_identity(value, label)
    contract, state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to {contract.get('root_task_id')!r}", code=4)
    if state.get("state") != "approved" or state.get("approval") != "recorded":
        refuse("planning requires an approved mission", code=5)
    target = f"{mission_id}::plan::{planner_session}::{invocation_id}"
    root = mission_dir(task_dir, mission_id)
    with mission_guard(task_dir, mission_id):
        cached = idempotency_check(root, idempotency_key, "mission_plan", target)
        if cached is not None:
            return dict(cached, replay=True)
        routed = mission_route(task_dir, root_task_id, mission_id, "planner")
        hoff = _load_sibling("atlas-handoff")
        spec, binary, unavailable = hoff.resolve_transport(routed["client"])
        if not binary or not isinstance(spec, dict):
            refuse(f"planner transport unavailable: {unavailable}", code=5)
        prompt = {
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "approved_scopes": [s["raw"] for s in contract["scopes"]],
            "max_slices": contract["max_slices"],
            "required_output": {
                "summary": "string",
                "steps": [{"scope": "one approved scope", "objective": "string"}],
                "tests": ["string"],
            },
            "instruction": "Return exactly one JSON object and nothing else. Inspect only "
                           "the approved files using read-only commands; never edit files, "
                           "write files, or access paths outside the approved scopes. "
                           "Choose only approved scopes. Treat directive or context files "
                           "as planning input, not executable steps; produce implementation "
                           "objectives for the files that must be changed, and do not emit "
                           "a step whose objective is only inspection.",
        }
        argv = [binary] + list(spec.get("argv") or [])
        timeout = int(spec.get("timeout") or 300)
        rc, stdout, stderr, timed_out, error_detail = hoff.run_transport_subprocess(
            argv, json.dumps(prompt, ensure_ascii=False, sort_keys=True), timeout)
        if timed_out or rc != 0 or error_detail:
            refuse(f"planner transport failed (returncode={rc}, timed_out={timed_out}): "
                   f"{error_detail or stderr.strip() or 'no detail'}", code=5)
        plan = _validate_plan(contract, _parse_json_object(stdout, "planner"))
        result = {"mission_id": mission_id, "root_task_id": root_task_id,
                  "planner_client": routed["client"], "planner_session": planner_session,
                  "invocation_id": invocation_id, "plan": plan,
                  "plan_path": str(root / "plan.json"), "replay": False}
        _atomic_write_json(root / "plan.json", result)
        audit_append(task_dir, mission_id, {"op": "mission_plan",
                     "planner_client": routed["client"], "planner_session": planner_session,
                     "invocation_id": invocation_id, "steps": len(plan["steps"])})
        idempotency_store(root, idempotency_key, "mission_plan", target, result)
        return result


def mission_validate(task_dir, root_task_id, mission_id):
    """Fail-closed structural validation of the whole approved mission contract. Never
    rewrites the contract, never invents a missing value, never changes approval. `valid` is
    true only when every check below finds nothing wrong."""
    findings = []
    contract, state = load_mission(task_dir, mission_id)

    if contract.get("root_task_id") != root_task_id:
        findings.append(f"mission belongs to root ticket "
                        f"{contract.get('root_task_id')!r}, not {root_task_id!r}")

    approved = state.get("state") == "approved" and state.get("approval") == "recorded"
    if not approved:
        findings.append(f"mission is not approved (state={state.get('state')!r}, "
                        f"approval={state.get('approval')!r})")
    elif state.get("approval_scope_hash") != _scope_hash(contract):
        findings.append("approval_scope_hash does not match a hash of the contract's "
                        "current scopes — approval evidence no longer matches the contract")

    for s in contract.get("scopes", []):
        try:
            canonicalize_scope(s.get("raw"))
        except MissionError as e:
            findings.append(f"scope {s.get('raw')!r} is invalid: {e}")

    for role in ROLES:
        field = ROLE_CONTRACT_FIELD[role]
        value = contract.get(field)
        if not value or not IDENTITY.fullmatch(str(value)):
            findings.append(f"{field} is not a valid client identity: {value!r}")

    try:
        require_budget_usd(contract.get("budget_usd"))
    except MissionError as e:
        findings.append(f"budget_usd is invalid: {e}")
    for key, label in (("max_slices", "max-slices"), ("max_attempts", "max-attempts"),
                       ("ttl_seconds", "ttl-seconds")):
        try:
            require_positive_int(contract.get(key), label)
        except MissionError as e:
            findings.append(f"{key} is invalid: {e}")

    allowed = set(contract.get("allowed_tools") or [])
    denied = set(contract.get("denied_tools") or [])
    overlap = allowed & denied
    if overlap:
        findings.append(f"allowed_tools and denied_tools overlap: {sorted(overlap)}")

    for key in ("forbidden_actions", "stop_conditions", "rollback_policy"):
        if not contract.get(key):
            findings.append(f"{key} is missing or empty")

    role_routing = {}
    if approved:
        for role in ROLES:
            try:
                role_routing[role] = dict(mission_route(task_dir, root_task_id, mission_id,
                                                        role), ok=True)
            except MissionError as e:
                role_routing[role] = {"ok": False, "role": role, "reason": str(e)}
                findings.append(f"role {role!r} does not route cleanly: {e}")
    else:
        for role in ROLES:
            role_routing[role] = {"ok": False, "role": role,
                                  "reason": "mission is not approved — routing was not "
                                            "attempted"}

    valid = not findings
    return {
        "mission_id": mission_id,
        "root_task_id": root_task_id,
        "valid": valid,
        "findings": findings,
        "role_routing": role_routing,
        "next_owner_action": (
            "mission contract is structurally valid and every role resolves; no automatic "
            "continuation exists — the owner still drives each step by hand"
            if valid else
            "resolve the listed findings before relying on this mission contract; nothing "
            "was rewritten automatically"),
    }


# ============================================================================================
# T-051-S3 — bounded foreground planner-to-executor handoff.
#
# `mission handoff` is the first command in this ticket that writes state beyond
# create/approve. It builds one deterministic PACKET (the bounded slice a planner would hand
# an executor) and one durable RECEIPT, entirely inside this mission's own
# `mission/<mission-id>/handoffs/` subtree, and records attempt/budget counters on this
# mission's own `state.json`. The mission's own `state` field never changes here (it stays
# `approved` — see T-051-S3-implementation.md "Why mission state stays `approved`" for why):
# this slice tracks bounded, owner-triggered, repeatable slice creation via counters, not a
# state-machine transition, so it commits to nothing about what a later slice's `planned`/
# `executing` states must mean.
#
# It NEVER: invokes a client, acquires a T-050 lease or file claim, writes a V6 handoff
# record under the ticket, approves anything, or selects a next mission/slice on its own —
# every call is one explicit, foreground, owner-issued command.
# ============================================================================================

def handoffs_root(task_dir, mission_id):
    """This mission's own handoff container — never a T-050 record, never a second
    authority. `mission/<mission-id>/handoffs/<handoff-id>/{packet,receipt}.json`."""
    return mission_dir(task_dir, mission_id) / "handoffs"


def handoff_dir(task_dir, mission_id, handoff_id):
    return handoffs_root(task_dir, mission_id) / handoff_id


def gen_handoff_id():
    return "handoff-" + uuid.uuid4().hex


def _require_gate(value, gates):
    """Reuses the existing bounded handoff/transport contract's own closed gate vocabulary
    (`cli/atlas-handoff.GATES`) rather than inventing a second one."""
    if value is None or not str(value).strip():
        refuse("--gate is required")
    value = str(value).strip()
    if value not in gates:
        refuse(f"--gate {value!r} is not one of the existing handoff gates: "
               f"{', '.join(gates)}")
    return value


def _require_exact_scope(contract, raw_scope):
    """Exact match only against this mission's own already-approved scopes — a handoff can
    never address a scope the owner did not already approve at `mission create` time."""
    if raw_scope is None or not str(raw_scope).strip():
        refuse("--scope is required and must be non-empty")
    raw_scope = str(raw_scope).strip()
    for s in contract.get("scopes", []):
        if s.get("raw") == raw_scope:
            return s
    refuse(f"--scope {raw_scope!r} is not one of this mission's approved scopes "
           f"({[s.get('raw') for s in contract.get('scopes', [])]}) — a handoff can only "
           f"address an already-approved scope, never a new one", code=5)


def mission_handoff(task_dir, root_task_id, mission_id, raw_scope, executor_client,
                    executor_session, invocation_id, gate, slice_budget_usd,
                    idempotency_key, objective=None):
    """One bounded, foreground, planner-to-executor handoff: a deterministic packet plus a
    durable receipt. Requires an approved mission. Resolves planner and executor through the
    existing T-051-S2 role resolution (`mission_route`) — never a hard-coded vendor name.
    Requires exact scope / client / session / invocation / gate / budget checks before
    returning a packet at all. Refuses a closed, unapproved, invalid, over-budget, ambiguous,
    or conflicting mission. Never approves, never invokes a client, never selects a next
    mission or slice, never touches Bash/network/MCP/Git/deletion/publication/credentials."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    executor_client = require_identity(executor_client, "executor-client")
    executor_session = require_identity(executor_session, "executor-session")
    invocation_id = require_identity(invocation_id, "invocation-id")
    slice_budget_usd = require_budget_usd(slice_budget_usd)
    if raw_scope is None or not str(raw_scope).strip():
        refuse("--scope is required and must be non-empty")
    raw_scope = str(raw_scope).strip()
    scan_credentials(raw_scope)

    # Reuses the existing bounded handoff/transport contract's own gate vocabulary —
    # read-only import, never a second copy of the gate list.
    hoff = _load_sibling("atlas-handoff")
    gate = _require_gate(gate, hoff.GATES)

    contract, _state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)

    # The idempotency target binds the key to this EXACT request, not merely to the mission
    # id (unlike create/approve, which only ever accept one call each) — a handoff may be
    # legitimately repeated (a retry, or a second bounded slice), so a reused key against a
    # materially different request must refuse as a conflicting replay, never silently
    # return a stale, mismatched result.
    idem_target = f"{mission_id}::{raw_scope}::{gate}::{invocation_id}::{executor_client}"

    with mission_guard(task_dir, mission_id):
        idem_root = handoffs_root(task_dir, mission_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_handoff", idem_target)
        if cached is not None:
            return dict(cached, replay=True)

        contract, state = load_mission(task_dir, mission_id)
        current_state = state.get("state")
        if current_state in ("blocked", "cancelled", "expired", "needs_owner"):
            refuse(f"mission {mission_id!r} is closed (state={current_state!r}) — a "
                   f"closed mission accepts no further handoff", code=5)
        if current_state != "approved" or state.get("approval") != "recorded":
            refuse(f"mission {mission_id!r} is in state {current_state!r} / approval "
                   f"{state.get('approval')!r} — a handoff requires an approved mission",
                   code=5)

        ttl_seconds = contract.get("ttl_seconds")
        approved_at_raw = state.get("approved_at")
        if approved_at_raw and isinstance(ttl_seconds, int):
            try:
                approved_at_dt = datetime.datetime.fromisoformat(approved_at_raw)
            except ValueError:
                approved_at_dt = None
            if approved_at_dt is not None:
                elapsed = (now_utc() - approved_at_dt).total_seconds()
                if elapsed > ttl_seconds:
                    refuse(f"mission {mission_id!r} ttl_seconds ({ttl_seconds}) elapsed "
                           f"{elapsed:.0f}s after approval — refusing a stale handoff",
                           code=5)

        scope = _require_exact_scope(contract, raw_scope)

        if executor_client != contract.get("executor_client"):
            refuse(f"--executor-client {executor_client!r} does not exactly match this "
                   f"mission's approved executor_client "
                   f"{contract.get('executor_client')!r} — refusing an ambiguous handoff",
                   code=5)

        try:
            planner_resolved = mission_route(task_dir, root_task_id, mission_id, "planner")
        except MissionError as e:
            refuse(f"planner role does not route cleanly — refusing an ambiguous handoff: "
                   f"{e}", code=5)
        try:
            executor_resolved = mission_route(task_dir, root_task_id, mission_id, "executor")
        except MissionError as e:
            refuse(f"executor role does not route cleanly — refusing an ambiguous handoff: "
                   f"{e}", code=5)

        handoffs_so_far = state.get("handoffs") or []
        attempts_used = int(state.get("attempts_used") or 0)
        max_attempts = contract.get("max_attempts")
        if isinstance(max_attempts, int) and attempts_used >= max_attempts:
            refuse(f"mission {mission_id!r} has used {attempts_used}/{max_attempts} "
                   f"attempts — max_attempts reached, refusing another handoff", code=5)

        distinct_scopes = {h.get("scope_canonical") for h in handoffs_so_far
                           if h.get("scope_canonical")}
        distinct_scopes.add(scope["canonical"])
        max_slices = contract.get("max_slices")
        if isinstance(max_slices, int) and len(distinct_scopes) > max_slices:
            refuse(f"mission {mission_id!r} would address "
                   f"{len(distinct_scopes)} distinct scopes, exceeding max_slices "
                   f"({max_slices}) — refusing another slice", code=5)

        budget_usd = contract.get("budget_usd")
        budget_committed = float(state.get("budget_committed_usd") or 0.0)
        remaining = budget_usd - budget_committed
        if slice_budget_usd > remaining + 1e-9:
            refuse(f"--slice-budget-usd {slice_budget_usd} exceeds this mission's "
                   f"remaining budget {remaining} (of {budget_usd} total, "
                   f"{budget_committed} already committed) — over-budget, refusing",
                   code=5)

        handoff_id = gen_handoff_id()
        created_at = iso(now_utc())
        new_attempts_used = attempts_used + 1
        new_budget_committed = budget_committed + slice_budget_usd
        new_remaining = budget_usd - new_budget_committed

        packet = {
            "handoff_id": handoff_id,
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "scope": scope,
            "planner_client": contract.get("planner_client"),
            "executor_client": contract.get("executor_client"),
            "executor_session": executor_session,
            "invocation_id": invocation_id,
            "gate": gate,
            "allowed_tools": list(contract.get("allowed_tools", [])),
            "denied_tools": list(contract.get("denied_tools", [])),
            "budget_usd": budget_usd,
            "slice_budget_usd": slice_budget_usd,
            "remaining_budget_usd": new_remaining,
            "max_attempts": max_attempts,
            "attempts_used": new_attempts_used,
            "max_slices": max_slices,
            "distinct_scopes_used": len(distinct_scopes),
            "stop_conditions": list(contract.get("stop_conditions", [])),
        }
        if objective:
            packet["objective"] = str(objective).strip()

        hd = handoff_dir(task_dir, mission_id, handoff_id)
        packet_path = hd / "packet.json"
        receipt_path = hd / "receipt.json"

        receipt = {
            "handoff_id": handoff_id,
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "idempotency_key": idempotency_key,
            "gate": gate,
            "planner_route": {
                "client": planner_resolved["client"],
                "adapter_id": planner_resolved["adapter_id"],
                "transport_id": planner_resolved["transport_id"],
                "transport_verified": planner_resolved["transport_verified"],
            },
            "executor_route": {
                "client": executor_resolved["client"],
                "adapter_id": executor_resolved["adapter_id"],
                "transport_id": executor_resolved["transport_id"],
                "transport_verified": executor_resolved["transport_verified"],
            },
            "packet_path": str(packet_path),
            "mission_state": "approved",
            "no_ai_invoked": True,
            "no_lease_or_claim_acquired": True,
            "no_v6_handoff_record_created_under_ticket": True,
            "no_automatic_approval": True,
            "no_continuation_loop": True,
            "next_action": (
                "owner-reviewed dispatch of this exact packet to the executor client is "
                "later-slice work (T-051-S4); no client was invoked by this command"),
        }

        _atomic_write_json(packet_path, packet)
        _atomic_write_json(receipt_path, receipt)

        new_state = dict(state)
        new_state.update({
            "attempts_used": new_attempts_used,
            "budget_committed_usd": new_budget_committed,
            "last_handoff_id": handoff_id,
            "handoffs": handoffs_so_far + [{
                "handoff_id": handoff_id, "scope_raw": scope["raw"],
                "scope_canonical": scope["canonical"], "gate": gate,
                "created_at": created_at,
            }],
            "updated_at": created_at,
        })
        _atomic_write_json(state_path(task_dir, mission_id), new_state)
        audit_append(task_dir, mission_id, {"op": "mission_handoff", "mission_id": mission_id,
                                            "root_task_id": root_task_id,
                                            "handoff_id": handoff_id, "gate": gate,
                                            "scope": scope["raw"]})

        result = {
            "mission_id": mission_id, "root_task_id": root_task_id,
            "handoff_id": handoff_id, "state": "approved",
            "packet_path": str(packet_path), "receipt_path": str(receipt_path),
            "attempts_used": new_attempts_used, "max_attempts": max_attempts,
            "budget_committed_usd": new_budget_committed,
            "remaining_budget_usd": new_remaining,
            "distinct_scopes_used": len(distinct_scopes), "max_slices": max_slices,
            "created_at": created_at,
        }
        idempotency_store(idem_root, idempotency_key, "mission_handoff", idem_target, result)
        return dict(result, replay=False)


# ============================================================================================
# T-051-S4 — structured result and verifier gate.
#
# `mission verify` is the only new command that writes. It takes one explicit, local
# `--result-file <path>` (a controlled, deterministic input channel — never stdin, never an
# environment variable, never a network fetch) containing the executor's claimed result for
# one existing handoff, validates it against that handoff's own T-051-S3 packet, and
# classifies it into exactly one of PASS / BLOCKED / FAILED / NEEDS_OWNER. Classification and
# evidence are persisted ONLY under this handoff's own
# `mission/<mission-id>/handoffs/<handoff-id>/{result,verification}.json` — never on the
# mission's own `state.json`, never anywhere under a T-050 record.
#
# `mission result` is the paired read-only inspector: it shows whatever `mission verify` has
# already persisted (or reports that nothing has been submitted yet) and never accepts new
# input itself.
#
# Neither command invokes a planner, an executor, or any client; neither acquires a T-050
# lease or file claim; neither approves anything, creates another handoff, or advances the
# mission toward a completed state. A `mission verify` call is one explicit, foreground,
# owner-issued command — never automatic, never chained.
# ============================================================================================

RESULT_STATUSES = ("pass", "blocked", "failed", "needs_owner")
CLASSIFICATIONS = ("PASS", "BLOCKED", "FAILED", "NEEDS_OWNER")

# A hard, defensive cap on the result file this command will ever read — large enough for any
# real bounded-slice result, small enough that a caller cannot hand this command an
# arbitrarily large file to read into memory.
MAX_RESULT_FILE_BYTES = 1_000_000

REQUIRED_RESULT_FIELDS = (
    "handoff_id", "mission_id", "root_task_id", "executor_client", "executor_session",
    "invocation_id", "gate", "scope", "status", "changed_files", "tests", "result_sha256",
    "reported_cost_usd", "summary",
)

RESULT_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")

NEXT_ACTION_BY_CLASSIFICATION = {
    "PASS": ("owner may review this PASS and decide whether to issue a further bounded "
             "mission handoff; nothing is automatic"),
    "BLOCKED": ("owner review required — this slice is blocked; nothing was approved or "
                "advanced automatically"),
    "FAILED": ("owner review required — this slice failed verification; nothing was "
               "approved or advanced automatically"),
    "NEEDS_OWNER": ("owner decision required — see owner_decision_required; nothing was "
                    "approved or advanced automatically"),
}


def result_path(task_dir, mission_id, handoff_id):
    return handoff_dir(task_dir, mission_id, handoff_id) / "result.json"


def verification_path(task_dir, mission_id, handoff_id):
    return handoff_dir(task_dir, mission_id, handoff_id) / "verification.json"


def verify_idem_dir(task_dir, mission_id, handoff_id):
    """Per-handoff, not per-mission — verification idempotency is naturally scoped to the one
    handoff it verifies."""
    return handoff_dir(task_dir, mission_id, handoff_id) / "verify-idempotency"


def handoff_guard(task_dir, mission_id, handoff_id):
    return _guard(handoff_dir(task_dir, mission_id, handoff_id) / ".verify.lock",
                 "mission-verify")


def _load_result_file(path_str):
    """Read, size-cap, credential-scan, then parse. Returns (raw_text, obj). Refuses (never
    partially returns) on a missing file, an oversized file, credential-shaped content, or
    anything that is not a JSON object — every one of these is a hard refusal: nothing is
    written, because there is nothing coherent yet to classify."""
    if not path_str or not str(path_str).strip():
        refuse("--result-file is required — missing result")
    p = Path(str(path_str).strip())
    if not p.is_file():
        refuse(f"--result-file {p} does not exist or is not a file — missing result", code=4)
    try:
        raw_text = p.read_text(errors="strict")
    except (OSError, UnicodeDecodeError) as e:
        refuse(f"--result-file {p} could not be read: {e} — missing result", code=4)
    if len(raw_text.encode("utf-8", errors="ignore")) > MAX_RESULT_FILE_BYTES:
        refuse(f"--result-file {p} exceeds the {MAX_RESULT_FILE_BYTES}-byte result size cap "
               f"— refusing rather than reading an unbounded input", code=2)
    # Scanned on the RAW text, before parsing: a credential could be embedded in any string
    # value, and this must never be persisted regardless of how the rest of the result reads.
    scan_credentials(raw_text)
    try:
        obj = json.loads(raw_text)
    except json.JSONDecodeError as e:
        refuse(f"--result-file {p} is not valid JSON — malformed result: {e}", code=2)
    if not isinstance(obj, dict):
        refuse(f"--result-file {p} is not a JSON object — malformed result", code=2)
    return raw_text, obj


def _validate_result_structure(result):
    """Structural validation only — shape, not content-correctness against the packet (that
    is `_identity_mismatches`/`_scope_expansion`/hash/budget, evaluated afterward and folded
    into a classification rather than a refusal). Returns the parsed, validated cost as a
    float. Refuses (hard) on anything so malformed there is nothing coherent to classify."""
    missing = [k for k in REQUIRED_RESULT_FIELDS if k not in result]
    if missing:
        refuse(f"result is missing required field(s): {', '.join(missing)} — malformed "
               f"result", code=2)
    status = result.get("status")
    if status not in RESULT_STATUSES:
        refuse(f"result status {status!r} is not one of {RESULT_STATUSES} — invalid status",
               code=2)
    if not isinstance(result.get("changed_files"), list) or not all(
            isinstance(x, str) for x in result["changed_files"]):
        refuse("result changed_files must be a list of strings — malformed result", code=2)
    if not isinstance(result.get("tests"), (list, str)):
        refuse("result tests must be a list of strings or a string — malformed result",
               code=2)
    if isinstance(result.get("tests"), list) and not all(
            isinstance(x, str) for x in result["tests"]):
        refuse("result tests list must contain only strings — malformed result", code=2)
    sha = result.get("result_sha256")
    if not isinstance(sha, str) or not RESULT_SHA_RE.fullmatch(sha):
        refuse("result result_sha256 must be a 64-character lowercase hex sha256 — malformed "
               "result", code=2)
    try:
        cost = float(result.get("reported_cost_usd"))
    except (TypeError, ValueError):
        refuse("result reported_cost_usd must be a finite non-negative number — malformed "
               "result", code=2)
    if not math.isfinite(cost) or cost < 0:
        refuse("result reported_cost_usd must be a finite non-negative number — malformed "
               "result", code=2)
    if not isinstance(result.get("summary"), str) or not result["summary"].strip():
        refuse("result summary must be a non-empty string — malformed result", code=2)
    if not isinstance(result.get("scope"), str) or not result["scope"].strip():
        refuse("result scope must be a non-empty string — malformed result", code=2)
    for label in ("handoff_id", "mission_id", "root_task_id", "executor_client",
                  "executor_session", "invocation_id", "gate"):
        if not isinstance(result.get(label), str) or not result[label].strip():
            refuse(f"result {label} must be a non-empty string — malformed result", code=2)
    if status == "blocked" and not (isinstance(result.get("blocker"), str)
                                    and result["blocker"].strip()):
        refuse("result status is 'blocked' but no non-empty blocker was given — malformed "
               "result", code=2)
    if status == "needs_owner" and not (isinstance(result.get("owner_decision_required"), str)
                                        and result["owner_decision_required"].strip()):
        refuse("result status is 'needs_owner' but no non-empty owner_decision_required was "
               "given — malformed result", code=2)
    scan_credentials(result.get("summary"), result.get("blocker"),
                     result.get("owner_decision_required"),
                     *(result.get("changed_files") or []),
                     *(result.get("tests") if isinstance(result.get("tests"), list) else
                       [result.get("tests")]))
    return cost


def _result_content_hash(result):
    """The one deterministic hash formula this command ever checks against: sha256 of a
    canonical (sorted-keys) JSON of exactly the result's own content fields — never a hash of
    real file contents this command has no way to independently observe. This catches
    transcription/corruption of the declared content, and gives every PASS/BLOCKED/FAILED/
    NEEDS_OWNER record one stable, recomputable, audit-checkable value."""
    material = {
        "handoff_id": result.get("handoff_id"),
        "mission_id": result.get("mission_id"),
        "root_task_id": result.get("root_task_id"),
        "status": result.get("status"),
        "changed_files": sorted(result.get("changed_files") or []),
        "tests": result.get("tests"),
        "summary": result.get("summary"),
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _identity_mismatches(result, packet):
    """Exact-match only, against the ORIGINAL packet this handoff was created with — never a
    fuzzy or partial comparison. Every field the S4 prompt names explicitly."""
    mismatches = []
    for field, expected in (
        ("handoff_id", packet.get("handoff_id")),
        ("mission_id", packet.get("mission_id")),
        ("root_task_id", packet.get("root_task_id")),
        ("executor_client", packet.get("executor_client")),
        ("executor_session", packet.get("executor_session")),
        ("invocation_id", packet.get("invocation_id")),
        ("gate", packet.get("gate")),
        ("scope", (packet.get("scope") or {}).get("raw")),
    ):
        if result.get(field) != expected:
            mismatches.append(f"{field}: packet declares {expected!r}, result declares "
                              f"{result.get(field)!r}")
    return mismatches


def _scope_expansion(result, packet):
    """Every `changed_files` entry must canonicalize to exactly the one scope this handoff was
    bounded to — anything else (a different file, an unsafe path, a directory) is scope
    expansion. An unsafe path is reported as an offender, never silently dropped or allowed
    through because it happened to fail canonicalization for an unrelated reason."""
    approved_canonical = (packet.get("scope") or {}).get("canonical")
    offenders = []
    for raw in result.get("changed_files") or []:
        try:
            c = canonicalize_scope(raw)
        except MissionError:
            offenders.append(raw)
            continue
        if c["canonical"] != approved_canonical:
            offenders.append(raw)
    return offenders


def _tests_present(tests_value):
    if isinstance(tests_value, str):
        return bool(tests_value.strip())
    return bool(tests_value)


def _classify_result(result, packet, identity_mismatches, hash_ok, tests_present,
                     scope_offenders, over_budget, budget_amounts):
    """One deterministic priority order, evaluated the same way every time: an objective
    verifier finding always overrides the executor's own self-reported `status` — a
    self-reported PASS is never trusted blindly. Returns (classification, checks,
    synthesized_blocker, synthesized_owner_decision)."""
    checks = [
        {"check": "identity_match", "ok": not identity_mismatches,
         "detail": identity_mismatches or None},
        {"check": "result_hash_match", "ok": hash_ok,
         "detail": None if hash_ok else "result_sha256 does not match the recomputed hash "
                                        "of the result's own declared content"},
        {"check": "scope_bounded", "ok": not scope_offenders,
         "detail": scope_offenders or None},
        {"check": "test_evidence_present", "ok": tests_present,
         "detail": None if tests_present else "tests field is empty — no test evidence was "
                                              "returned"},
        {"check": "within_budget", "ok": not over_budget,
         "detail": None if not over_budget else
         f"reported_cost_usd {budget_amounts[0]} exceeds this slice's own budget "
         f"{budget_amounts[1]}"},
    ]

    synthesized_blocker = None
    synthesized_owner_decision = None

    if identity_mismatches:
        classification = "NEEDS_OWNER"
        synthesized_owner_decision = (
            "the returned result's own identity fields do not exactly match this handoff's "
            "packet — confirm this result actually belongs to this bounded slice before "
            "trusting it")
    elif not hash_ok:
        classification = "FAILED"
    elif scope_offenders:
        classification = "BLOCKED"
        synthesized_blocker = (f"the executor reported changes outside the approved scope: "
                               f"{scope_offenders}")
    elif not tests_present:
        classification = "NEEDS_OWNER"
        synthesized_owner_decision = (
            "no test evidence was returned for this slice — confirm the change is safe "
            "before relying on it")
    elif over_budget:
        classification = "NEEDS_OWNER"
        synthesized_owner_decision = (
            f"reported_cost_usd {budget_amounts[0]} exceeds this slice's own budget "
            f"{budget_amounts[1]} — an owner budget decision is required")
    elif result.get("status") == "blocked":
        classification = "BLOCKED"
    elif result.get("status") == "failed":
        classification = "FAILED"
    elif result.get("status") == "needs_owner":
        classification = "NEEDS_OWNER"
    else:
        classification = "PASS"

    return classification, checks, synthesized_blocker, synthesized_owner_decision


def mission_verify(task_dir, root_task_id, mission_id, handoff_id, result_file,
                   idempotency_key):
    """Validate one executor-returned result against its own T-051-S3 packet and classify it
    into exactly one of PASS/BLOCKED/FAILED/NEEDS_OWNER. Persists `result.json` (the result,
    verbatim, as submitted) and `verification.json` (this function's own generated report)
    only under `mission/<mission-id>/handoffs/<handoff-id>/` — never on the mission's own
    `state.json`, never a T-050 record. Never invokes a client, never acquires a lease or
    claim, never approves anything, never creates another handoff, never changes the mission
    toward a completed state."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    if not handoff_id or not IDENTITY.fullmatch(str(handoff_id)):
        refuse(f"not a handoff id: {handoff_id!r}")
    handoff_id = str(handoff_id)

    contract, state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)
    if state.get("state") in ("blocked", "cancelled", "expired", "needs_owner"):
        refuse(f"mission {mission_id!r} is closed (state={state.get('state')!r}) — a "
               f"closed mission accepts no further verification", code=5)

    hd = handoff_dir(task_dir, mission_id, handoff_id)
    packet, corrupt = _read_json(hd / "packet.json")
    if packet is None:
        refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
               + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)

    raw_text, result = _load_result_file(result_file)
    cost = _validate_result_structure(result)

    content_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    idem_target = f"{mission_id}::{handoff_id}::{content_hash}"

    with handoff_guard(task_dir, mission_id, handoff_id):
        idem_root = verify_idem_dir(task_dir, mission_id, handoff_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_verify", idem_target)
        if cached is not None:
            return dict(cached, replay=True)

        # Re-read fresh under the guard, mirroring create/approve/handoff's own convention.
        packet, corrupt = _read_json(hd / "packet.json")
        if packet is None:
            refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
                   + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)

        identity_mismatches = _identity_mismatches(result, packet)
        expected_hash = _result_content_hash(result)
        hash_ok = (result.get("result_sha256") == expected_hash)
        tests_present = _tests_present(result.get("tests"))
        scope_offenders = _scope_expansion(result, packet)
        slice_budget = float(packet.get("slice_budget_usd") or 0.0)
        over_budget = cost > slice_budget + 1e-9

        classification, checks, synth_blocker, synth_owner = _classify_result(
            result, packet, identity_mismatches, hash_ok, tests_present, scope_offenders,
            over_budget, (cost, slice_budget))

        created_at = iso(now_utc())
        result_record = dict(result)

        verification = {
            "handoff_id": handoff_id,
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "idempotency_key": idempotency_key,
            "classification": classification,
            "checks": checks,
            "expected_result_sha256": expected_hash,
            "declared_result_sha256": result.get("result_sha256"),
            "identity_mismatches": identity_mismatches,
            "scope_offenders": scope_offenders,
            "reported_cost_usd": cost,
            "slice_budget_usd": slice_budget,
            "blocker": result.get("blocker") or synth_blocker,
            "owner_decision_required": result.get("owner_decision_required") or synth_owner,
            "no_ai_invoked": True,
            "no_lease_or_claim_acquired": True,
            "no_v6_handoff_record_created_under_ticket": True,
            "no_automatic_approval": True,
            "no_automatic_completion": True,
            "no_next_handoff_created": True,
            "no_continuation_loop": True,
            "next_action": NEXT_ACTION_BY_CLASSIFICATION[classification],
        }

        _atomic_write_json(result_path(task_dir, mission_id, handoff_id), result_record)
        _atomic_write_json(verification_path(task_dir, mission_id, handoff_id), verification)
        audit_append(task_dir, mission_id, {"op": "mission_verify", "mission_id": mission_id,
                                            "root_task_id": root_task_id,
                                            "handoff_id": handoff_id,
                                            "classification": classification})

        out = {
            "mission_id": mission_id, "root_task_id": root_task_id,
            "handoff_id": handoff_id, "classification": classification,
            "result_path": str(result_path(task_dir, mission_id, handoff_id)),
            "verification_path": str(verification_path(task_dir, mission_id, handoff_id)),
            "created_at": created_at,
        }
        idempotency_store(idem_root, idempotency_key, "mission_verify", idem_target, out)
        return dict(out, replay=False)


RESULT_NOT_SUBMITTED_ACTION = (
    "no result has been submitted yet for this handoff — run `mission verify "
    "<root-task-id> <mission-id> <handoff-id> --result-file <path> "
    "--idempotency-key <key>` with the executor's returned result file")


# ============================================================================================
# T-051-S5 — safe foreground continuation loop (mission continue).
#
# `mission continue` is the only new command in this slice, and the only mutating one. It
# creates AT MOST ONE next bounded handoff (same S3 packet/receipt shape) from an existing
# handoff whose T-051-S4 verification classified EXACTLY "PASS" — never "pass" the raw
# self-reported status, always the verifier's own final `classification` field. Every check
# T-051-S3 already made for a handoff is re-run here from scratch against the CURRENT
# contract/state (never trusted from the previous call): mission approval, mission state,
# approval scope hash, ttl, max_attempts, max_slices, total budget, the exact approved scope,
# the exact contract executor identity, and — new to this slice — the previous handoff's own
# executor_session (a continuation may never move to a different session/authority than the
# one already verified) and all three roles' routing (planner/executor/verifier).
#
# This function NEVER: invokes a client, dispatches or sends anything, acquires a T-050 lease
# or file claim, writes a V6 handoff record, approves anything, marks the mission completed,
# selects a different ticket, or calls itself / any other mutating mission function — every
# call is one explicit, foreground, owner-issued command, and it produces at most one new
# handoff. It is a self-contained, independent function (the module's own established
# convention — see the docstrings for T-051-S1..S4 above) rather than a wrapper around
# `mission_handoff`, so a change to S3's function can never silently change continuation
# behavior, and vice versa.
# ============================================================================================

def continuation_idem_dir(task_dir, mission_id):
    """A dedicated idempotency namespace for `mission continue`, separate from
    `handoffs/idempotency/` (T-051-S3's own namespace for `mission handoff`) so a key reused
    across the two commands is never ambiguous with a real handoff replay."""
    return mission_dir(task_dir, mission_id) / "continuation-idempotency"


def _require_previous_evidence(task_dir, mission_id, previous_handoff_id):
    """Loads the previous handoff's own packet.json, result.json, and verification.json —
    read-only, never rewritten. Refuses, with a distinct reason for each case, on a missing
    handoff, missing result/verification evidence, or a malformed/corrupt verification
    record. Never guesses a classification from a self-reported status; only the verifier's
    own persisted `classification` field is ever trusted."""
    if not previous_handoff_id or not IDENTITY.fullmatch(str(previous_handoff_id)):
        refuse(f"not a handoff id: {previous_handoff_id!r}")
    previous_handoff_id = str(previous_handoff_id)
    hd = handoff_dir(task_dir, mission_id, previous_handoff_id)

    packet, corrupt = _read_json(hd / "packet.json")
    if packet is None:
        refuse(f"no handoff {previous_handoff_id!r} for mission {mission_id!r}"
               + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)

    result, r_corrupt = _read_json(hd / "result.json")
    verification, v_corrupt = _read_json(hd / "verification.json")
    if verification is None:
        refuse(f"handoff {previous_handoff_id!r} has no verification evidence"
               + (" (corrupt verification.json)" if v_corrupt else " (no verification.json — "
                  "run `mission verify` first)") + " — missing verification evidence, "
               f"refusing continuation", code=5)
    if result is None:
        refuse(f"handoff {previous_handoff_id!r} has verification.json but no readable "
               f"result.json" + (" (corrupt)" if r_corrupt else " (missing)") + " — missing "
               f"test evidence, refusing continuation", code=5)

    classification = verification.get("classification")
    if classification not in CLASSIFICATIONS:
        refuse(f"handoff {previous_handoff_id!r} has a malformed verification record "
               f"(classification={classification!r}, not one of {CLASSIFICATIONS}) — "
               f"malformed verification evidence, refusing continuation", code=5)
    if verification.get("mission_id") != mission_id or packet.get("mission_id") != mission_id:
        refuse(f"handoff {previous_handoff_id!r} evidence belongs to a different mission — "
               f"identity-mismatched, refusing continuation", code=5)
    if verification.get("handoff_id") != previous_handoff_id or \
            packet.get("handoff_id") != previous_handoff_id:
        refuse(f"handoff {previous_handoff_id!r} evidence does not identify itself "
               f"consistently — identity-mismatched, refusing continuation", code=5)

    if classification != "PASS":
        refuse(f"handoff {previous_handoff_id!r} classified {classification} (not PASS) — "
               f"refusing continuation. next action for that handoff was: "
               f"{verification.get('next_action')!r}", code=5)

    return packet, result, verification


def mission_continue(task_dir, root_task_id, mission_id, previous_handoff_id, raw_scope,
                     executor_client, executor_session, invocation_id, gate,
                     slice_budget_usd, idempotency_key, objective=None):
    """Create at most one next bounded handoff, only when the referenced handoff's own
    T-051-S4 verification classified exactly PASS, and only while every mission limit and
    every contract boundary still holds under the CURRENT contract/state — never the state
    the previous handoff was created against. Writes a new packet.json + receipt.json (same
    S3 shape) plus a deterministic continuation-receipt.json, all only under the new handoff's
    own `mission/<mission-id>/handoffs/<new-handoff-id>/` directory. Never rewrites the
    previous handoff's own packet.json or verification.json. Never invokes a client, never
    acquires a lease or claim, never approves anything, never marks the mission completed,
    never selects a different ticket, never loops."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    executor_client = require_identity(executor_client, "executor-client")
    executor_session = require_identity(executor_session, "executor-session")
    invocation_id = require_identity(invocation_id, "invocation-id")
    slice_budget_usd = require_budget_usd(slice_budget_usd)
    if not previous_handoff_id or not IDENTITY.fullmatch(str(previous_handoff_id)):
        refuse(f"not a handoff id: {previous_handoff_id!r}")
    previous_handoff_id = str(previous_handoff_id)
    if raw_scope is None or not str(raw_scope).strip():
        refuse("--scope is required and must be non-empty")
    raw_scope = str(raw_scope).strip()
    scan_credentials(raw_scope)

    hoff = _load_sibling("atlas-handoff")
    gate = _require_gate(gate, hoff.GATES)

    contract, _state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)

    idem_target = (f"{mission_id}::continue::{previous_handoff_id}::{raw_scope}::{gate}::"
                  f"{invocation_id}::{executor_client}::{executor_session}")

    with mission_guard(task_dir, mission_id):
        idem_root = continuation_idem_dir(task_dir, mission_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_continue", idem_target)
        if cached is not None:
            return dict(cached, replay=True)

        # Re-read the mission fresh under the guard, mirroring create/approve/handoff/verify's
        # own convention — nothing here trusts a value read before the guard was acquired.
        contract, state = load_mission(task_dir, mission_id)
        current_state = state.get("state")
        if current_state in ("blocked", "cancelled", "expired", "needs_owner"):
            refuse(f"mission {mission_id!r} is closed (state={current_state!r}) — a closed "
                   f"mission accepts no continuation", code=5)
        if current_state != "approved" or state.get("approval") != "recorded":
            refuse(f"mission {mission_id!r} is in state {current_state!r} / approval "
                   f"{state.get('approval')!r} — continuation requires an approved mission",
                   code=5)
        if state.get("approval_scope_hash") != _scope_hash(contract):
            refuse(f"mission {mission_id!r} approval_scope_hash no longer matches the "
                   f"contract's current scopes — approval evidence is stale, refusing "
                   f"continuation", code=5)

        ttl_seconds = contract.get("ttl_seconds")
        approved_at_raw = state.get("approved_at")
        stop_ttl = "ok"
        if approved_at_raw and isinstance(ttl_seconds, int):
            try:
                approved_at_dt = datetime.datetime.fromisoformat(approved_at_raw)
            except ValueError:
                approved_at_dt = None
            if approved_at_dt is not None:
                elapsed = (now_utc() - approved_at_dt).total_seconds()
                if elapsed > ttl_seconds:
                    refuse(f"mission {mission_id!r} ttl_seconds ({ttl_seconds}) elapsed "
                           f"{elapsed:.0f}s after approval — ttl expired, refusing "
                           f"continuation", code=5)

        previous_packet, _previous_result, previous_verification = _require_previous_evidence(
            task_dir, mission_id, previous_handoff_id)
        previous_classification = previous_verification.get("classification")

        if executor_client != contract.get("executor_client"):
            refuse(f"--executor-client {executor_client!r} does not exactly match this "
                   f"mission's approved executor_client "
                   f"{contract.get('executor_client')!r} — identity-mismatched, refusing "
                   f"continuation", code=5)
        if executor_session != previous_packet.get("executor_session"):
            refuse(f"--executor-session {executor_session!r} does not match the previous "
                   f"handoff's own executor_session "
                   f"{previous_packet.get('executor_session')!r} — a continuation may never "
                   f"move to a different session/authority than the one already verified, "
                   f"refusing", code=5)

        scope = _require_exact_scope(contract, raw_scope)

        try:
            planner_resolved = mission_route(task_dir, root_task_id, mission_id, "planner")
        except MissionError as e:
            refuse(f"planner role does not route cleanly — refusing an ambiguous "
                   f"continuation: {e}", code=5)
        try:
            executor_resolved = mission_route(task_dir, root_task_id, mission_id, "executor")
        except MissionError as e:
            refuse(f"executor role does not route cleanly — refusing an ambiguous "
                   f"continuation: {e}", code=5)
        try:
            verifier_resolved = mission_route(task_dir, root_task_id, mission_id, "verifier")
        except MissionError as e:
            refuse(f"verifier role does not route cleanly — refusing an ambiguous "
                   f"continuation: {e}", code=5)

        handoffs_so_far = state.get("handoffs") or []
        attempts_before = int(state.get("attempts_used") or 0)
        max_attempts = contract.get("max_attempts")
        stop_max_attempts = "ok"
        if isinstance(max_attempts, int) and attempts_before >= max_attempts:
            refuse(f"mission {mission_id!r} has used {attempts_before}/{max_attempts} "
                   f"attempts — max_attempts reached, refusing continuation", code=5)

        distinct_scopes = {h.get("scope_canonical") for h in handoffs_so_far
                           if h.get("scope_canonical")}
        distinct_scopes.add(scope["canonical"])
        max_slices = contract.get("max_slices")
        stop_max_slices = "ok"
        if isinstance(max_slices, int) and len(distinct_scopes) > max_slices:
            refuse(f"mission {mission_id!r} would address {len(distinct_scopes)} distinct "
                   f"scopes, exceeding max_slices ({max_slices}) — max_slices reached, "
                   f"refusing continuation", code=5)

        budget_usd = contract.get("budget_usd")
        budget_before = float(state.get("budget_committed_usd") or 0.0)
        remaining_before = budget_usd - budget_before
        stop_budget = "ok"
        if slice_budget_usd > remaining_before + 1e-9:
            refuse(f"--slice-budget-usd {slice_budget_usd} exceeds this mission's remaining "
                   f"budget {remaining_before} (of {budget_usd} total, {budget_before} "
                   f"already committed) — budget would be exceeded, refusing continuation",
                   code=5)

        # Tools are never expanded: the new packet's allowed/denied tools are the contract's
        # own current fields, verbatim — never widened, never taken from the request.
        allowed_tools = list(contract.get("allowed_tools", []))
        denied_tools = list(contract.get("denied_tools", []))
        if allowed_tools != list(previous_packet.get("allowed_tools") or []) or \
                denied_tools != list(previous_packet.get("denied_tools") or []):
            refuse("this mission's allowed_tools/denied_tools no longer match the previous "
                   "handoff's own packet — a continuation may never observe a different tool "
                   "boundary than the one already approved, refusing", code=5)

        new_handoff_id = gen_handoff_id()
        created_at = iso(now_utc())
        attempts_after = attempts_before + 1
        budget_after = budget_before + slice_budget_usd
        remaining_after = budget_usd - budget_after

        packet = {
            "handoff_id": new_handoff_id,
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "scope": scope,
            "planner_client": contract.get("planner_client"),
            "executor_client": contract.get("executor_client"),
            "executor_session": executor_session,
            "invocation_id": invocation_id,
            "gate": gate,
            "allowed_tools": allowed_tools,
            "denied_tools": denied_tools,
            "budget_usd": budget_usd,
            "slice_budget_usd": slice_budget_usd,
            "remaining_budget_usd": remaining_after,
            "max_attempts": max_attempts,
            "attempts_used": attempts_after,
            "max_slices": max_slices,
            "distinct_scopes_used": len(distinct_scopes),
            "stop_conditions": list(contract.get("stop_conditions", [])),
            "continued_from_handoff_id": previous_handoff_id,
        }
        if objective:
            packet["objective"] = str(objective).strip()

        hd = handoff_dir(task_dir, mission_id, new_handoff_id)
        packet_path = hd / "packet.json"
        receipt_path = hd / "receipt.json"
        continuation_receipt_path = hd / "continuation-receipt.json"

        receipt = {
            "handoff_id": new_handoff_id,
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "idempotency_key": idempotency_key,
            "gate": gate,
            "continued_from_handoff_id": previous_handoff_id,
            "planner_route": {
                "client": planner_resolved["client"],
                "adapter_id": planner_resolved["adapter_id"],
                "transport_id": planner_resolved["transport_id"],
                "transport_verified": planner_resolved["transport_verified"],
            },
            "executor_route": {
                "client": executor_resolved["client"],
                "adapter_id": executor_resolved["adapter_id"],
                "transport_id": executor_resolved["transport_id"],
                "transport_verified": executor_resolved["transport_verified"],
            },
            "verifier_route": {
                "client": verifier_resolved["client"],
                "adapter_id": verifier_resolved["adapter_id"],
                "transport_id": verifier_resolved["transport_id"],
                "transport_verified": verifier_resolved["transport_verified"],
            },
            "packet_path": str(packet_path),
            "mission_state": "approved",
            "no_ai_invoked": True,
            "no_lease_or_claim_acquired": True,
            "no_v6_handoff_record_created_under_ticket": True,
            "no_automatic_approval": True,
            "no_automatic_completion": True,
            "no_dispatch_or_send": True,
            "no_continuation_loop": True,
            "next_action": (
                "owner-reviewed dispatch of this exact packet to the executor client is "
                "later-slice work (T-051-S7); no client was invoked by this command"),
        }

        stop_condition_evaluation = {
            "ttl_seconds": stop_ttl,
            "max_attempts": stop_max_attempts,
            "max_slices": stop_max_slices,
            "budget_usd": stop_budget,
        }

        continuation_receipt = {
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": created_at,
            "previous_handoff_id": previous_handoff_id,
            "previous_classification": previous_classification,
            "new_handoff_id": new_handoff_id,
            "selected_scope": scope,
            "planner_identity": planner_resolved["client"],
            "executor_identity": executor_resolved["client"],
            "verifier_identity": verifier_resolved["client"],
            "attempts_before": attempts_before,
            "attempts_after": attempts_after,
            "budget_committed_before_usd": budget_before,
            "budget_committed_after_usd": budget_after,
            "stop_condition_evaluation": stop_condition_evaluation,
            "owner_decision_required": (
                "none — this continuation created one bounded handoff inside the existing "
                "mission contract; the owner still decides whether/when to dispatch it, and "
                "still decides completion"),
            "no_ai_invoked": True,
            "no_lease_or_claim_acquired": True,
            "no_v6_handoff_record_created_under_ticket": True,
            "no_automatic_approval": True,
            "no_automatic_completion": True,
            "no_ticket_selection": True,
            "no_dispatch_or_send": True,
            "no_continuation_loop": True,
        }

        _atomic_write_json(packet_path, packet)
        _atomic_write_json(receipt_path, receipt)
        _atomic_write_json(continuation_receipt_path, continuation_receipt)

        new_state = dict(state)
        new_state.update({
            "attempts_used": attempts_after,
            "budget_committed_usd": budget_after,
            "last_handoff_id": new_handoff_id,
            "handoffs": handoffs_so_far + [{
                "handoff_id": new_handoff_id, "scope_raw": scope["raw"],
                "scope_canonical": scope["canonical"], "gate": gate,
                "created_at": created_at, "continued_from_handoff_id": previous_handoff_id,
            }],
            "updated_at": created_at,
        })
        _atomic_write_json(state_path(task_dir, mission_id), new_state)
        audit_append(task_dir, mission_id, {
            "op": "mission_continue", "mission_id": mission_id, "root_task_id": root_task_id,
            "previous_handoff_id": previous_handoff_id,
            "previous_classification": previous_classification,
            "handoff_id": new_handoff_id, "gate": gate, "scope": scope["raw"],
        })

        result = {
            "mission_id": mission_id, "root_task_id": root_task_id,
            "previous_handoff_id": previous_handoff_id,
            "previous_classification": previous_classification,
            "handoff_id": new_handoff_id, "state": "approved",
            "packet_path": str(packet_path), "receipt_path": str(receipt_path),
            "continuation_receipt_path": str(continuation_receipt_path),
            "attempts_used": attempts_after, "max_attempts": max_attempts,
            "budget_committed_usd": budget_after, "remaining_budget_usd": remaining_after,
            "distinct_scopes_used": len(distinct_scopes), "max_slices": max_slices,
            "created_at": created_at,
        }
        idempotency_store(idem_root, idempotency_key, "mission_continue", idem_target, result)
        return dict(result, replay=False)


def mission_result_view(task_dir, root_task_id, mission_id, handoff_id):
    """Entirely read-only: shows whatever `mission verify` has already persisted for this
    handoff, or reports that nothing has been submitted yet. Never accepts a result itself,
    never writes anything, never changes any state."""
    contract, _state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)
    if not handoff_id or not IDENTITY.fullmatch(str(handoff_id)):
        refuse(f"not a handoff id: {handoff_id!r}")
    handoff_id = str(handoff_id)

    hd = handoff_dir(task_dir, mission_id, handoff_id)
    packet, corrupt = _read_json(hd / "packet.json")
    if packet is None:
        refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
               + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)

    result, r_corrupt = _read_json(result_path(task_dir, mission_id, handoff_id))
    verification, v_corrupt = _read_json(verification_path(task_dir, mission_id, handoff_id))

    if result is None and verification is None:
        return {
            "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
            "has_result": False, "classification": None, "result": None, "verification": None,
            "next_owner_action": RESULT_NOT_SUBMITTED_ACTION,
        }
    if verification is None:
        refuse(f"handoff {handoff_id!r} has a result.json but no readable "
               f"verification.json" + (" (corrupt)" if v_corrupt else " (missing)"), code=5)
    if result is None:
        refuse(f"handoff {handoff_id!r} has a verification.json but no readable result.json"
               + (" (corrupt)" if r_corrupt else " (missing)"), code=5)

    return {
        "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
        "has_result": True,
        "classification": verification.get("classification"),
        "result": result,
        "verification": verification,
        "next_owner_action": verification.get("next_action"),
    }


# ============================================================================================
# T-051-S6 — completion, failure, and notification packet.
#
# `mission finalize` is the only new command in this slice, and the only mutating one. It
# reads one existing handoff's own T-051-S4 `verification.json` — never a raw executor
# `status` — and, once every mission limit and every piece of evidence checks out, writes
# exactly one set of durable final packets under the mission's OWN directory (never under a
# handoff's own directory, since these are mission-level, not slice-level, artifacts) and
# moves the mission into exactly one of the four terminal states task.md's own state diagram
# already names: `completed` (PASS only, and only once every completion condition is proven
# from the persisted evidence, never merely from the classification label), `blocked`,
# `failed`, `needs_owner`.
#
# This function NEVER: invokes a client, dispatches or sends anything, acquires a T-050
# lease or file claim, writes a V6 handoff record, approves anything, creates a new handoff,
# deletes any existing mission evidence, or calls itself. It writes at most once per mission
# — every terminal state in `TERMINAL_STATES` refuses a second, non-replay finalize attempt.
# It is a self-contained function, following the same independence convention every T-051
# slice before it has used.
# ============================================================================================

FINAL_STATE_BY_CLASSIFICATION = {
    "PASS": "completed",
    "BLOCKED": "blocked",
    "FAILED": "failed",
    "NEEDS_OWNER": "needs_owner",
}

FINAL_OWNER_ACTION_BY_CLASSIFICATION = {
    "PASS": ("mission completed — every completion condition (identity, hash, scope, test "
             "evidence, budget) was independently reconfirmed from the persisted "
             "verification evidence, not merely read off its classification label. Owner "
             "may review final-report.json, the changed files, and the tests; nothing "
             "further is automatic."),
    "BLOCKED": ("owner review required — this mission stopped BLOCKED. See "
               "blocker-packet.json for the exact boundary violation. Nothing was approved "
               "or advanced automatically."),
    "FAILED": ("owner review required — this mission stopped FAILED. See "
              "blocker-packet.json for the evidence mismatch. Nothing was approved or "
              "advanced automatically."),
    "NEEDS_OWNER": ("owner decision required — see owner-decision-packet.json. Nothing was "
                    "approved or advanced automatically; this mission cannot proceed "
                    "without an explicit owner decision."),
}


def final_dir(task_dir, mission_id):
    """Mission-level final packets — never a handoff's own directory, never a T-050
    record. `mission/<mission-id>/final/{final-report,session-summary,notification-packet,
    blocker-packet,owner-decision-packet}.json`."""
    return mission_dir(task_dir, mission_id) / "final"


def finalize_idem_dir(task_dir, mission_id):
    return mission_dir(task_dir, mission_id) / "finalize-idempotency"


def _load_handoff_evidence_for_finalize(task_dir, mission_id, handoff_id):
    """Independent of T-051-S5's `_require_previous_evidence` (same reasoning as every other
    independent copy in this file): loads one handoff's packet/result/verification and
    refuses, with a distinct reason, on every malformed or missing case — but, unlike S5's
    continuation gate, does NOT require the classification to be PASS. `mission finalize`
    accepts any of the four classifications; what it refuses on is missing or self-
    contradictory evidence, never a particular (non-ambiguous) classification value."""
    if not handoff_id or not IDENTITY.fullmatch(str(handoff_id)):
        refuse(f"not a handoff id: {handoff_id!r}")
    handoff_id = str(handoff_id)
    hd = handoff_dir(task_dir, mission_id, handoff_id)

    packet, corrupt = _read_json(hd / "packet.json")
    if packet is None:
        refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
               + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)

    result, r_corrupt = _read_json(hd / "result.json")
    verification, v_corrupt = _read_json(hd / "verification.json")
    if verification is None:
        refuse(f"handoff {handoff_id!r} has no verification evidence"
               + (" (corrupt verification.json)" if v_corrupt else " (no verification.json "
                  "— run `mission verify` first)") + " — missing verification evidence, "
               f"refusing finalize", code=5)
    if result is None:
        refuse(f"handoff {handoff_id!r} has verification.json but no readable result.json"
               + (" (corrupt)" if r_corrupt else " (missing)") + " — missing result "
               f"evidence, refusing finalize", code=5)

    classification = verification.get("classification")
    if classification not in CLASSIFICATIONS:
        refuse(f"handoff {handoff_id!r} has a malformed verification record "
               f"(classification={classification!r}, not one of {CLASSIFICATIONS}) — "
               f"malformed verification evidence, refusing finalize", code=5)
    if verification.get("mission_id") != mission_id or packet.get("mission_id") != mission_id:
        refuse(f"handoff {handoff_id!r} evidence belongs to a different mission — "
               f"identity-mismatched, refusing finalize", code=5)
    if verification.get("handoff_id") != handoff_id or packet.get("handoff_id") != handoff_id:
        refuse(f"handoff {handoff_id!r} evidence does not identify itself consistently — "
               f"identity-mismatched, refusing finalize", code=5)

    return packet, result, verification


def _recompute_classification_from_verification(verification, result):
    """The one contradiction check this command runs: recompute what S4's own fixed
    priority order (`_classify_result`) would have produced from the persisted evidence
    (the `checks` list's own `ok` flags, plus the result's own self-reported `status` as the
    lowest-priority tiebreaker — identical priority order to `_classify_result`), and compare
    it to the `classification` field actually persisted. A mismatch means the verification
    record contradicts itself — never trusted, refused rather than guessed which one is
    right."""
    check_ok = {c.get("check"): c.get("ok") for c in (verification.get("checks") or [])
               if isinstance(c, dict)}
    identity_ok = check_ok.get("identity_match", True)
    hash_ok = check_ok.get("result_hash_match", True)
    scope_ok = check_ok.get("scope_bounded", True)
    tests_ok = check_ok.get("test_evidence_present", True)
    budget_ok = check_ok.get("within_budget", True)

    if not identity_ok:
        return "NEEDS_OWNER"
    if not hash_ok:
        return "FAILED"
    if not scope_ok:
        return "BLOCKED"
    if not tests_ok:
        return "NEEDS_OWNER"
    if not budget_ok:
        return "NEEDS_OWNER"
    status = (result or {}).get("status")
    if status == "blocked":
        return "BLOCKED"
    if status == "failed":
        return "FAILED"
    if status == "needs_owner":
        return "NEEDS_OWNER"
    return "PASS"


def _completion_conditions_proven(verification):
    """PASS may become `completed` only when every completion condition is independently
    reconfirmed from the persisted `checks` list — never merely because the classification
    label says PASS. Returns (proven: bool, failing_checks: list[str])."""
    checks = verification.get("checks") or []
    failing = [c.get("check") for c in checks
              if isinstance(c, dict) and c.get("ok") is not True]
    return (not failing), failing


def mission_finalize(task_dir, root_task_id, mission_id, handoff_id, idempotency_key):
    """Read one handoff's own T-051-S4 verification, and — only once every mission limit,
    every piece of evidence, and every completion condition checks out — write exactly one
    set of durable final packets under this mission's own `mission/<mission-id>/final/`
    directory and move the mission into exactly one terminal state (`completed`, `blocked`,
    `failed`, `needs_owner`). Never invokes a client, never creates a handoff, never
    dispatches or sends, never acquires a lease or claim, never deletes any existing
    evidence, never rewrites owner approval evidence."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    if not handoff_id or not IDENTITY.fullmatch(str(handoff_id)):
        refuse(f"not a handoff id: {handoff_id!r}")
    handoff_id = str(handoff_id)

    contract, _state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)

    idem_target = f"{mission_id}::finalize::{handoff_id}"

    with mission_guard(task_dir, mission_id):
        idem_root = finalize_idem_dir(task_dir, mission_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_finalize", idem_target)
        if cached is not None:
            return dict(cached, replay=True)

        contract, state = load_mission(task_dir, mission_id)
        current_state = state.get("state")
        if current_state in TERMINAL_STATES:
            refuse(f"mission {mission_id!r} is already finalized (state={current_state!r}) "
                   f"— a mission is finalized at most once; this is not an idempotent "
                   f"replay of the original finalize request", code=5)
        if current_state != "approved" or state.get("approval") != "recorded":
            refuse(f"mission {mission_id!r} is in state {current_state!r} / approval "
                   f"{state.get('approval')!r} — finalize requires an approved mission",
                   code=5)
        if state.get("approval_scope_hash") != _scope_hash(contract):
            refuse(f"mission {mission_id!r} approval_scope_hash no longer matches the "
                   f"contract's current scopes — approval evidence is stale, refusing "
                   f"finalize", code=5)

        ttl_seconds = contract.get("ttl_seconds")
        approved_at_raw = state.get("approved_at")
        if approved_at_raw and isinstance(ttl_seconds, int):
            try:
                approved_at_dt = datetime.datetime.fromisoformat(approved_at_raw)
            except ValueError:
                approved_at_dt = None
            if approved_at_dt is not None:
                elapsed = (now_utc() - approved_at_dt).total_seconds()
                if elapsed > ttl_seconds:
                    refuse(f"mission {mission_id!r} ttl_seconds ({ttl_seconds}) elapsed "
                           f"{elapsed:.0f}s after approval — ttl expired, refusing "
                           f"finalize", code=5)

        packet, result, verification = _load_handoff_evidence_for_finalize(
            task_dir, mission_id, handoff_id)

        # Unresolved previous handoff: every OTHER handoff this mission has ever created
        # must already carry its own verification evidence before this mission may be
        # finalized — a dangling, never-verified handoff is exactly the ambiguity this
        # command must stop on rather than silently ignore.
        handoffs_so_far = state.get("handoffs") or []
        for h in handoffs_so_far:
            other_id = h.get("handoff_id")
            if not other_id or other_id == handoff_id:
                continue
            other_verification, other_corrupt = _read_json(
                handoff_dir(task_dir, mission_id, other_id) / "verification.json")
            if other_verification is None:
                refuse(f"mission {mission_id!r} has an unresolved previous handoff "
                       f"{other_id!r} with no verification evidence"
                       + (" (corrupt)" if other_corrupt else "") + " — refusing finalize "
                       f"until every handoff is resolved", code=5)

        # Mission limits, revalidated from the CURRENT contract/state — never trusted from
        # whatever they were when the handoff being finalized was created.
        attempts_used = int(state.get("attempts_used") or 0)
        max_attempts = contract.get("max_attempts")
        if isinstance(max_attempts, int) and attempts_used > max_attempts:
            refuse(f"mission {mission_id!r} attempts_used ({attempts_used}) exceeds "
                   f"max_attempts ({max_attempts}) — a mission limit was violated, "
                   f"refusing finalize", code=5)
        distinct_scopes = {h.get("scope_canonical") for h in handoffs_so_far
                           if h.get("scope_canonical")}
        max_slices = contract.get("max_slices")
        if isinstance(max_slices, int) and len(distinct_scopes) > max_slices:
            refuse(f"mission {mission_id!r} has used {len(distinct_scopes)} distinct "
                   f"scopes, exceeding max_slices ({max_slices}) — a mission limit was "
                   f"violated, refusing finalize", code=5)
        budget_usd = contract.get("budget_usd")
        budget_committed = float(state.get("budget_committed_usd") or 0.0)
        if budget_committed > budget_usd + 1e-9:
            refuse(f"mission {mission_id!r} budget_committed_usd ({budget_committed}) "
                   f"exceeds budget_usd ({budget_usd}) — a mission limit was violated, "
                   f"refusing finalize", code=5)
        try:
            _require_exact_scope(contract, packet.get("scope", {}).get("raw"))
        except MissionError as e:
            refuse(f"the handoff being finalized addresses a scope outside this mission's "
                   f"current approved scopes — {e}", code=5)
        if packet.get("executor_client") != contract.get("executor_client"):
            refuse(f"the handoff being finalized names executor_client "
                   f"{packet.get('executor_client')!r}, which no longer matches this "
                   f"mission's approved executor_client "
                   f"{contract.get('executor_client')!r} — identity-mismatched, refusing "
                   f"finalize", code=5)

        # Contradictory verification: recompute S4's own classification from the persisted
        # checks and compare — never trust the stored `classification` field blindly either.
        recomputed = _recompute_classification_from_verification(verification, result)
        persisted_classification = verification.get("classification")
        if recomputed != persisted_classification:
            refuse(f"handoff {handoff_id!r}'s verification evidence is contradictory: its "
                   f"own checks recompute to {recomputed}, but its persisted "
                   f"classification is {persisted_classification!r} — refusing finalize "
                   f"rather than trusting either blindly", code=5)

        final_classification = persisted_classification
        new_mission_state = FINAL_STATE_BY_CLASSIFICATION[final_classification]

        if final_classification == "PASS":
            proven, failing = _completion_conditions_proven(verification)
            if not proven:
                refuse(f"handoff {handoff_id!r} classified PASS but its own checks list "
                       f"has unproven condition(s) {failing} — completion conditions are "
                       f"not proven, refusing finalize", code=5)

        # ---- everything checks out: build the final packets ----
        all_handoff_ids = [h.get("handoff_id") for h in handoffs_so_far if h.get("handoff_id")]
        all_classifications = {}
        for hid in all_handoff_ids:
            v, _c = _read_json(handoff_dir(task_dir, mission_id, hid) / "verification.json")
            all_classifications[hid] = v.get("classification") if v else None

        finalized_at = iso(now_utc())
        stop_condition = {
            "PASS": f"verifier classification PASS on handoff {handoff_id!r}; every "
                    f"completion condition proven",
            "BLOCKED": f"verifier classification BLOCKED on handoff {handoff_id!r}: "
                      f"{verification.get('blocker')}",
            "FAILED": f"verifier classification FAILED on handoff {handoff_id!r}",
            "NEEDS_OWNER": f"verifier classification NEEDS_OWNER on handoff {handoff_id!r}: "
                          f"{verification.get('owner_decision_required')}",
        }[final_classification]

        common = {
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "finalized_at": finalized_at,
            "final_handoff_id": handoff_id,
            "all_handoff_ids": all_handoff_ids,
            "all_verified_classifications": all_classifications,
            "final_classification": final_classification,
            "mission_state": new_mission_state,
            "approved_scope": packet.get("scope", {}).get("raw"),
            "changed_files": result.get("changed_files", []),
            "tests": result.get("tests"),
            "reported_cost_usd": result.get("reported_cost_usd"),
            "budget_committed_usd": budget_committed,
            "budget_usd": budget_usd,
            "attempts_used": attempts_used,
            "max_attempts": max_attempts,
            "slices_used": len(distinct_scopes),
            "max_slices": max_slices,
            "stop_condition": stop_condition,
            "rollback_policy": contract.get("rollback_policy"),
            "owner_action": FINAL_OWNER_ACTION_BY_CLASSIFICATION[final_classification],
            "no_ai_invoked": True,
            "no_lease_or_claim_acquired": True,
            "no_v6_handoff_record_created_under_ticket": True,
            "no_automatic_approval": True,
            "no_new_handoff_created": True,
            "no_dispatch_or_send": True,
            "no_evidence_deleted": True,
        }

        final_report = dict(common)

        session_summary = {
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "finalized_at": finalized_at,
            "final_classification": final_classification,
            "mission_state": new_mission_state,
            "handoff_count": len(all_handoff_ids),
            "attempts_used": attempts_used,
            "max_attempts": max_attempts,
            "budget_committed_usd": budget_committed,
            "budget_usd": budget_usd,
            "owner_action": common["owner_action"],
            "next_owner_action": NEXT_OWNER_ACTION.get(new_mission_state),
        }

        notification_packet = {
            "mission_id": mission_id,
            "root_task_id": root_task_id,
            "created_at": finalized_at,
            "final_classification": final_classification,
            "mission_state": new_mission_state,
            "message": (f"mission {mission_id} for ticket {root_task_id} finalized as "
                       f"{new_mission_state} ({final_classification})"),
            "is_signal_only": True,
            "no_automatic_action": True,
            "no_os_notification": True,
            "no_desktop_notification": True,
            "no_webhook": True,
            "no_network_call": True,
        }

        hd_final = final_dir(task_dir, mission_id)
        final_report_path = hd_final / "final-report.json"
        session_summary_path = hd_final / "session-summary.json"
        notification_packet_path = hd_final / "notification-packet.json"
        blocker_packet_path = hd_final / "blocker-packet.json"
        owner_decision_packet_path = hd_final / "owner-decision-packet.json"

        _atomic_write_json(final_report_path, final_report)
        _atomic_write_json(session_summary_path, session_summary)
        _atomic_write_json(notification_packet_path, notification_packet)

        written_paths = {
            "final_report_path": str(final_report_path),
            "session_summary_path": str(session_summary_path),
            "notification_packet_path": str(notification_packet_path),
            "blocker_packet_path": None,
            "owner_decision_packet_path": None,
        }

        if final_classification in ("BLOCKED", "FAILED"):
            blocker_packet = {
                "mission_id": mission_id,
                "root_task_id": root_task_id,
                "created_at": finalized_at,
                "final_handoff_id": handoff_id,
                "final_classification": final_classification,
                "blocker": verification.get("blocker"),
                "scope_offenders": verification.get("scope_offenders", []),
                "identity_mismatches": verification.get("identity_mismatches", []),
                "checks": verification.get("checks", []),
                "owner_action": common["owner_action"],
                "rollback_policy": contract.get("rollback_policy"),
            }
            _atomic_write_json(blocker_packet_path, blocker_packet)
            written_paths["blocker_packet_path"] = str(blocker_packet_path)

        if final_classification == "NEEDS_OWNER":
            owner_decision_packet = {
                "mission_id": mission_id,
                "root_task_id": root_task_id,
                "created_at": finalized_at,
                "final_handoff_id": handoff_id,
                "final_classification": final_classification,
                "owner_decision_required": verification.get("owner_decision_required"),
                "identity_mismatches": verification.get("identity_mismatches", []),
                "checks": verification.get("checks", []),
                "owner_action": common["owner_action"],
            }
            _atomic_write_json(owner_decision_packet_path, owner_decision_packet)
            written_paths["owner_decision_packet_path"] = str(owner_decision_packet_path)

        new_state = dict(state)
        new_state.update({
            "state": new_mission_state,
            "finalized_at": finalized_at,
            "final_handoff_id": handoff_id,
            "final_classification": final_classification,
            "updated_at": finalized_at,
        })
        _atomic_write_json(state_path(task_dir, mission_id), new_state)
        audit_append(task_dir, mission_id, {
            "op": "mission_finalize", "mission_id": mission_id, "root_task_id": root_task_id,
            "handoff_id": handoff_id, "final_classification": final_classification,
            "mission_state": new_mission_state,
        })

        result_out = {
            "mission_id": mission_id, "root_task_id": root_task_id,
            "handoff_id": handoff_id, "final_classification": final_classification,
            "mission_state": new_mission_state, "finalized_at": finalized_at,
            **written_paths,
        }
        idempotency_store(idem_root, idempotency_key, "mission_finalize", idem_target,
                          result_out)
        return dict(result_out, replay=False)


# ============================================================================================
# T-051-S7 live pilot — scope-aware mission-pilot transport argv resolution.
#
# `claude-code-tools-pilot` (in the real handoff-transports.yaml, untouched by this section)
# is hard-coded to one historical trial directory (`projects/atlas/tickets/AIOS-012`) and
# cannot safely be reused for an arbitrary mission's own approved scope. This section adds
# the smallest possible bounded mechanism to fix that, WITHOUT touching that entry, WITHOUT
# adding a second transport registry, and WITHOUT this file ever dispatching anything itself:
#
#   - `MISSION_PILOT_SCOPE_DIR_PLACEHOLDER` is the one fixed, documented token a transport's
#     argv may contain (see the new `claude-code-mission-pilot` entry).
#   - `resolve_mission_pilot_directory` derives ONE canonical, symlink-resolved directory
#     from ONE already-approved scope — never a hard-coded path, never more than one
#     directory, never anything outside the Atlas root, never the Atlas root itself (too
#     broad for a single-file pilot).
#   - `build_mission_pilot_argv` substitutes that one placeholder, and only that exact
#     token, into an existing transport's own declared argv list — every other element
#     passes through unexamined and un-substituted. This is not a template engine: there is
#     exactly one substitutable token, and its value is always a directory that has already
#     passed every check above.
#   - `mission_pilot_transport_argv` ties the two together against one real T-051 handoff's
#     own packet, read-only, never invoking anything, never gated on the transport's own
#     `verified` flag — this is deliberate: this function's whole purpose is to produce the
#     exact argv an owner-run trial would use to GENERATE the evidence that later justifies
#     setting `verified: true` by hand (see handoff-transports.yaml's own "Enabling one"
#     section). No function in this file calls it automatically, and no function in this
#     file ever calls `subprocess` against its result — mission_handoff/mission_continue/
#     mission_verify/mission_finalize still never dispatch, exactly as every prior slice's
#     record already states.
# ============================================================================================

MISSION_PILOT_SCOPE_DIR_PLACEHOLDER = "__MISSION_SCOPE_DIR__"
MISSION_PILOT_BUDGET_PLACEHOLDER = "__MISSION_BUDGET_USD__"


def resolve_mission_pilot_directory(scope):
    """`scope` must be exactly the ONE already-canonicalized scope dict
    (`{"raw": ..., "canonical": ...}`) a single T-051 handoff is bound to — never a
    mission's full multi-scope list, and never raw user input. Returns the canonical,
    symlink-resolved parent directory of that one approved file, as a string. Fails closed
    on every ambiguity T-051-S7's live-transport requirements name:

    - empty/missing scope
    - more than one distinct directory (a defensive check: this function only ever accepts
      one scope, but refuses explicitly rather than silently picking one if ever called
      with more)
    - a directory that does not re-resolve to itself under `os.path.realpath` (a symlink
      component the original scope canonicalization did not already collapse)
    - a directory outside the Atlas root
    - the Atlas root itself (a single approved file never justifies handing a client the
      entire Atlas home directory)
    """
    scopes = [scope] if isinstance(scope, dict) else list(scope or [])
    if not scopes:
        refuse("no approved scope given — empty scope, refusing to derive a mission pilot "
               "directory", code=2)
    dirs = set()
    for s in scopes:
        if not isinstance(s, dict) or not s.get("canonical"):
            refuse("scope has no canonical file path — ambiguous scope, refusing to derive "
                   "a mission pilot directory", code=2)
        dirs.add(str(Path(s["canonical"]).parent))
    if len(dirs) != 1:
        refuse(f"scope resolves to {len(dirs)} distinct director{'y' if len(dirs) == 1 else 'ies'} "
               f"{sorted(dirs)} — multiple unrelated directories, refusing an ambiguous "
               f"mission pilot directory", code=5)
    directory = dirs.pop()

    home_real = str(Path(os.path.realpath(str(atlas_home()))))
    dir_real = str(Path(os.path.realpath(directory)))
    if dir_real != directory:
        refuse(f"scope directory {directory!r} resolves to a different path once symlinks "
               f"are followed ({dir_real!r}) — refusing rather than trusting an "
               f"unresolved value", code=5)
    try:
        Path(dir_real).relative_to(home_real)
    except ValueError:
        refuse(f"scope directory {dir_real} resolves outside the allowed Atlas root "
               f"{home_real} — a symlink or otherwise escaping directory, refusing",
               code=5)
    if dir_real == home_real:
        refuse("scope resolves directly to the Atlas root itself — too broad a directory "
               "for a bounded single-file mission pilot, refusing", code=5)
    return dir_real


def build_mission_pilot_argv(binary, argv_template, scope, slice_budget_usd=None):
    """Substitutes the ONE fixed `MISSION_PILOT_SCOPE_DIR_PLACEHOLDER` token — and only that
    exact token — with the directory `resolve_mission_pilot_directory` derives from `scope`.
    Every other element of `argv_template` is copied through byte-for-byte, never examined,
    never substituted, never shell-interpreted (the result is a plain argv list, exactly
    like every other transport in this registry). Refuses if the placeholder does not
    appear in the template exactly once — this is not a general-purpose template engine,
    and a transport declaring zero or several placeholders is a configuration error, not
    something this function silently tolerates."""
    if not isinstance(argv_template, list) or not all(isinstance(a, str) for a in argv_template):
        refuse("transport argv must be a list of strings", code=5)
    directory = resolve_mission_pilot_directory(scope)
    out = []
    substituted = 0
    budget_substituted = 0
    if slice_budget_usd is not None:
        try:
            budget = float(slice_budget_usd)
        except (TypeError, ValueError):
            refuse("mission slice budget is not numeric — refusing executor invocation", code=5)
        if budget <= 0:
            refuse("mission slice budget must be positive — refusing executor invocation", code=5)
    for a in argv_template:
        if a == MISSION_PILOT_SCOPE_DIR_PLACEHOLDER:
            out.append(directory)
            substituted += 1
        elif a == MISSION_PILOT_BUDGET_PLACEHOLDER:
            if slice_budget_usd is None:
                refuse("transport requires a mission budget but none was supplied", code=5)
            out.append(f"{budget:.2f}")
            budget_substituted += 1
        else:
            out.append(a)
    if substituted != 1:
        refuse(f"transport argv must contain the {MISSION_PILOT_SCOPE_DIR_PLACEHOLDER!r} "
               f"placeholder exactly once; found it {substituted} time(s) — refusing an "
               f"ambiguous or unbounded argv template", code=5)
    if slice_budget_usd is not None and budget_substituted != 1:
        refuse(f"transport argv must contain the {MISSION_PILOT_BUDGET_PLACEHOLDER!r} "
               f"placeholder exactly once; found it {budget_substituted} time(s) — refusing "
               f"a static or ambiguous spend cap", code=5)
    if not binary or not isinstance(binary, str) or re.search(r"[\s;|&$<>]", binary):
        refuse(f"transport names no plain binary: {binary!r}", code=5)
    return [binary] + out


def mission_pilot_transport_argv(task_dir, mission_id, handoff_id,
                                 client="claude-code-mission-pilot"):
    """Read-only. Resolves `client`'s registered transport entry (via the existing
    `atlas-handoff` registry — no second registry, no new registry file) and this handoff's
    own single approved scope, and returns the fully-substituted argv list a caller could
    invoke — this function itself never invokes anything, never checks `verified` (its
    purpose is to produce the exact argv an owner-run trial uses to generate the evidence
    `verified: true` requires), and is never called by mission_handoff, mission_continue,
    mission_verify, or mission_finalize, none of which dispatch."""
    contract, _state = load_mission(task_dir, mission_id)
    hd = handoff_dir(task_dir, mission_id, handoff_id)
    packet, corrupt = _read_json(hd / "packet.json")
    if packet is None:
        refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
               + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)
    scope = packet.get("scope")
    if not isinstance(scope, dict) or not scope.get("canonical"):
        refuse(f"handoff {handoff_id!r} has no valid scope on its own packet — "
               f"empty/ambiguous scope, refusing", code=2)

    hoff = _load_sibling("atlas-handoff")
    transports = hoff.load_transports()
    spec = transports.get(client)
    if not isinstance(spec, dict):
        refuse(f"no transport is declared for client {client!r} in {hoff.TRANSPORTS}",
               code=4)
    argv_template = spec.get("argv")
    binary = spec.get("binary")
    return build_mission_pilot_argv(binary, argv_template, scope,
                                    (packet.get("slice_budget_usd") or None))


# ============================================================================================
# T-051-S7 execution integration — `mission execute`.
#
# Everything above this section (S1-S7-pilot) was already true before this addition: a bounded
# handoff packet exists, a scope-aware argv can be built for `claude-code-mission-pilot`, and a
# real invocation was proven possible by hand in a test. What was still missing is the one
# thing an owner would actually run: a single mission command that loads an existing handoff,
# revalidates it from scratch, resolves its executor through the existing (never bypassed)
# transport-verification gate, invokes exactly one bounded foreground subprocess, and converts
# whatever comes back into the existing S4 result/verification contract — never a second,
# parallel classifier.
#
# `mission_execute` is the only new function here, and the only one that calls `subprocess`.
# It never approves, never expands scope/tools/identity, never selects a different client or
# ticket, never creates a lease or claim, never retries, and never runs in the background. It
# delegates every classification decision to the existing `mission_verify` (imported nowhere —
# it is a sibling function in this same module, called directly, so there is exactly one
# priority-ordered classifier in this file, not two).
# ============================================================================================

# The content fields a live executor is asked to state about its own work. Identity fields
# (handoff_id, mission_id, root_task_id, executor_client, executor_session, invocation_id,
# gate, scope) are also required in the executor's own JSON reply, but only so mission_verify's
# existing identity_match check has something to compare against — never trusted blindly, and
# never used to skip that check.
EXECUTOR_REPLY_CONTENT_FIELDS = ("status", "changed_files", "tests", "summary")
EXECUTOR_REPLY_IDENTITY_FIELDS = ("handoff_id", "mission_id", "root_task_id", "executor_client",
                                 "executor_session", "invocation_id", "gate", "scope")

# A hard cap on captured stdout/stderr this command will ever persist — the same defensive
# posture as MAX_RESULT_FILE_BYTES above, sized for a bounded single-file pilot reply.
MAX_EXECUTOR_OUTPUT_BYTES = 2_000_000

MISSION_EXECUTE_PROMPT_TEMPLATE = """You are a bounded mission executor invoked in one \
single foreground call. Below is a JSON packet describing your one allowed task.

Rules, with no exception:
- The only file you may Read or Edit is the file named by this packet's own "scope" field \
(its "raw" path, resolved under the current working directory you were started in).
- Never read, edit, or list any other file or directory. Never run a shell command. Never \
access the network. Never use any tool other than Read and Edit.
- Read that one file first, then follow the packet's "objective" exactly when it is present. \
If no objective is present, the file itself must state exactly what change to make. Make no \
other change.
- After editing, your ENTIRE reply must be exactly one JSON object and nothing else — no \
prose, no markdown fences, no explanation before or after it. It must have exactly these \
keys: handoff_id, mission_id, root_task_id, executor_client, executor_session, invocation_id, \
gate, scope, status, changed_files, tests, reported_cost_usd, summary.
- Copy handoff_id, mission_id, root_task_id, executor_client, executor_session, invocation_id, \
and gate EXACTLY as given in the packet below — character for character.
- For "scope", copy ONLY the packet's scope.raw value (a plain file path string) — NOT the \
whole scope object. Your reply's "scope" field must be a plain string, e.g. "some/file.txt", \
never a JSON object.
- Set "status" to "pass" if you completed the edit exactly as the file instructed; otherwise \
"blocked" (if the instructions asked for something outside the rules above), "failed" (if the \
edit could not be completed), or "needs_owner" (if the instructions were ambiguous).
- Set "changed_files" to a JSON list containing exactly the one scope path you edited (or an \
empty list if you made no edit).
- Set "tests" to a short JSON list of strings describing how you confirmed the edit (e.g. \
"read the file back and compared its content").
- Set "reported_cost_usd" to your best-effort numeric estimate of this call's cost in US \
dollars.
- Set "summary" to one short sentence describing what you did.
- Do not include a result_sha256 field — it is computed separately, outside your reply.

PACKET:
{packet_json}
"""


def execution_dir(task_dir, mission_id, handoff_id):
    """Everything `mission execute` writes lives only here, under the target handoff's own
    directory — never on the mission's own state.json, never under a T-050 record, never a
    second store."""
    return handoff_dir(task_dir, mission_id, handoff_id) / "execution"


def raw_return_path(task_dir, mission_id, handoff_id):
    return execution_dir(task_dir, mission_id, handoff_id) / "raw-return.json"


def execute_idem_dir(task_dir, mission_id, handoff_id):
    """A dedicated idempotency namespace for `mission execute`, separate from both
    `handoffs/verify-idempotency` (T-051-S4's own namespace) and `continuation-idempotency`
    (T-051-S5's own) — same established convention, a reused key across commands is never
    ambiguous with a different command's replay."""
    return handoff_dir(task_dir, mission_id, handoff_id) / "execute-idempotency"


def _parse_executor_reply(raw_stdout):
    """A deterministic, fail-closed parser for whatever the executor process printed on
    stdout: (candidate_content_dict_or_None, malformed_reason_or_None). Only ever returns a
    candidate when the reply is a single JSON object carrying every field this function
    checks for by name — never a partial/best-effort guess at a malformed reply. Content is
    read, never interpreted or executed; nothing here trusts a self-reported result_sha256
    (mission_execute recomputes it independently below) or a self-reported identity field
    blindly (mission_verify's own identity_match check still runs against the packet)."""
    text = (raw_stdout or "").strip()
    if not text:
        return None, "executor produced no output on stdout"
    lines = text.splitlines()
    if len(lines) >= 3 and lines[0].strip() in ("```", "```json") and lines[-1].strip() == "```":
        text = "\n".join(lines[1:-1]).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"executor stdout is not valid JSON: {e}"
    if not isinstance(obj, dict):
        return None, "executor stdout is not a JSON object"
    missing = [k for k in EXECUTOR_REPLY_CONTENT_FIELDS + EXECUTOR_REPLY_IDENTITY_FIELDS
              if k not in obj]
    if missing:
        return None, f"executor reply is missing required field(s): {', '.join(missing)}"
    return obj, None


def _synthetic_execute_result(packet, status, summary, tests_note=None):
    """Built entirely by this command, never by the executor — used only when the executor's
    own reply could not be classified at all (timeout, non-zero exit, subprocess error, or a
    malformed reply). Carries the SAME identity fields as the handoff's own packet (so
    mission_verify's identity_match check passes cleanly) and a zero reported cost (nothing was
    usefully returned to charge for). `result_sha256` is computed the same way a real reply's
    is: independently, over exactly the fields `_result_content_hash` reads."""
    material = {
        "handoff_id": packet["handoff_id"],
        "mission_id": packet["mission_id"],
        "root_task_id": packet["root_task_id"],
        "executor_client": packet["executor_client"],
        "executor_session": packet["executor_session"],
        "invocation_id": packet["invocation_id"],
        "gate": packet["gate"],
        "scope": packet["scope"]["raw"],
        "status": status,
        "changed_files": [],
        "tests": tests_note or ["mission execute: no test evidence — see summary"],
        "reported_cost_usd": 0.0,
        "summary": summary,
    }
    if status == "blocked":
        material["blocker"] = summary
    if status == "needs_owner":
        material["owner_decision_required"] = summary
    material["result_sha256"] = _result_content_hash(material)
    return material


def _build_execute_candidate(packet, candidate_content):
    """Assembles one S4-shaped result record from an executor reply that already passed
    `_parse_executor_reply`. `result_sha256` is always computed HERE, independently, from the
    content fields the executor declared — never trusted from the executor's own reply (an
    LLM asked to hand-compute a cryptographic hash is not a meaningful integrity check; this
    command signs the declared content itself, the same way a scribe's transcription doesn't
    require the speaker to also dictate a checksum). Every identity field is still copied
    through EXACTLY as the executor stated it — a wrong identity field here is exactly what
    mission_verify's own identity_match check is for, and this function never resolves that
    disagreement itself."""
    cost = candidate_content.get("reported_cost_usd")
    try:
        cost = float(cost)
        if not math.isfinite(cost) or cost < 0:
            cost = 0.0
    except (TypeError, ValueError):
        cost = 0.0
    changed_files = candidate_content.get("changed_files")
    if not isinstance(changed_files, list) or not all(isinstance(x, str) for x in changed_files):
        changed_files = []
    tests = candidate_content.get("tests")
    if not isinstance(tests, (list, str)):
        tests = []
    # A common, harmless executor mistake: echoing the packet's own "scope" object
    # ({"raw": ..., "canonical": ...}) verbatim instead of just its "raw" string, exactly as
    # instructed. Normalized here, deterministically, before mission_verify ever sees it — this
    # is data assembly, not a classification decision, so it does not touch identity_match or
    # any other verifier rule: a scope that is wrong in a way this normalization does not fix
    # (or a scope object without a "raw" key) is left as-is and correctly refused downstream.
    scope_value = candidate_content.get("scope")
    if isinstance(scope_value, dict):
        scope_value = scope_value.get("raw")
    material = {
        "handoff_id": candidate_content.get("handoff_id"),
        "mission_id": candidate_content.get("mission_id"),
        "root_task_id": candidate_content.get("root_task_id"),
        "executor_client": candidate_content.get("executor_client"),
        "executor_session": candidate_content.get("executor_session"),
        "invocation_id": candidate_content.get("invocation_id"),
        "gate": candidate_content.get("gate"),
        "scope": scope_value,
        "status": candidate_content.get("status"),
        "changed_files": changed_files,
        "tests": tests,
        "reported_cost_usd": cost,
        "summary": candidate_content.get("summary"),
    }
    material["result_sha256"] = _result_content_hash(material)
    return material


def _classify_execution(task_dir, root_task_id, mission_id, handoff_id, packet,
                        candidate_content, malformed_reason, verify_idempotency_key,
                        fallback_status):
    """The ONE place execution outcomes turn into a classification, and it does so entirely
    by calling the existing `mission_verify` — never by re-implementing PASS/BLOCKED/FAILED/
    NEEDS_OWNER priority rules a second time. Writes the candidate result file under this
    handoff's own `execution/` directory (never anywhere mission_verify itself wouldn't
    already write to), then delegates. If mission_verify itself refuses the candidate as
    structurally malformed (a possibility even after `_parse_executor_reply`'s presence check
    — e.g. a non-string field), that refusal is caught and converted into the same synthetic,
    fail-closed fallback path used for a timeout/non-zero-exit/unparsable reply, so this
    command always ends with a real, persisted classification rather than an uncaught
    exception."""
    ed = execution_dir(task_dir, mission_id, handoff_id)
    candidate_path = ed / "verify-candidate.json"

    if candidate_content is not None and malformed_reason is None:
        candidate = _build_execute_candidate(packet, candidate_content)
        _atomic_write_json(candidate_path, candidate)
        try:
            return mission_verify(task_dir, root_task_id, mission_id, handoff_id,
                                  str(candidate_path), verify_idempotency_key)
        except MissionError as e:
            malformed_reason = f"executor reply failed verifier structural validation: {e}"

    synthetic = _synthetic_execute_result(
        packet, status=fallback_status,
        summary=f"mission execute: {malformed_reason}")
    _atomic_write_json(candidate_path, synthetic)
    return mission_verify(task_dir, root_task_id, mission_id, handoff_id, str(candidate_path),
                          verify_idempotency_key)


# T-051-S7-R1: the exact T-050 lease/claim TTL margin added on top of the transport's own
# declared subprocess timeout, so the lease does not expire mid-call under normal operation.
# This is a scheduling margin only — it never widens scope, tools, or identity, and it never
# substitutes for TTL/attempt/budget revalidation, which mission_execute already performs
# above, from the CURRENT contract/state, before this margin is even computed.
LEASE_TTL_BUFFER_SECONDS = 120


def _coord():
    """Load `cli/atlas_coordination.py` as a library module — the identical `_load_sibling`
    technique this file already uses for `cli/atlas-handoff`/`cli/atlas-adapter`, and the
    identical technique `cli/atlas-coordinator._coord()` uses for the same file. This is the
    ONE place `mission_execute` reaches into T-050's own lease/claim implementation; nothing
    in this module re-implements lease or claim logic, and nothing here writes to
    `cli/atlas_coordination.py` or to any T-050 record directly — every mutation below is a
    plain call into that file's own, unmodified, already-tested functions."""
    return _load_sibling("atlas_coordination.py")


def _execute_sub_key(idempotency_key, purpose):
    """A short, opaque, deterministic sub-key derived from this execute call's own
    idempotency key plus a fixed purpose label, so the lease/claim/lease-cleanup/claim-
    cleanup primitives each get their own idempotency namespace instead of colliding on one
    literal string. Identical derivation to `cli/atlas-coordinator._sub_key` (independent copy,
    for the same reason every helper in this file is kept independent of the coordinator/
    coordination files: a change to one must never silently change the other)."""
    digest = hashlib.sha256(f"{idempotency_key}:{purpose}".encode()).hexdigest()[:48]
    return f"sk-{digest}"


def _execute_coordination_failure(task_dir, root_task_id, mission_id, handoff_id, packet,
                                  stage, detail, idem_root, idempotency_key, idem_target,
                                  lease_info=None, claim_info=None, cleanup=None):
    """The one path used when a T-050 lease or file claim could not be acquired at all
    (`stage` is `lease_acquire` or `claim_acquire`), or when post-execution cleanup of a
    lease/claim this attempt itself acquired did not fully complete (`stage` is `cleanup`).
    Writes the same deterministic evidence location `mission_execute` always writes to
    (`execution/raw-return.json`) with `invoked: false`, classifies via the existing
    `_classify_execution` -> `mission_verify` path (never a second classifier — every
    BLOCKED classification in this command, whatever its cause, is produced the one same
    way), and stores the mission-execute-level idempotency record exactly like every other
    outcome, so a replay of this exact request returns this exact BLOCKED result without a
    second lease/claim/subprocess mutation. Never claims a file after a lease failure, never
    retries a failed release, and always reports a cleanup failure explicitly rather than
    silently swallowing it."""
    raw_return = {
        "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
        "invoked": False, "stage": stage, "detail": detail,
        "single_foreground_call": False, "no_retry": True,
    }
    if lease_info is not None:
        raw_return["lease"] = lease_info
    if claim_info is not None:
        raw_return["claim"] = claim_info
    if cleanup is not None:
        raw_return["cleanup"] = cleanup
    _atomic_write_json(raw_return_path(task_dir, mission_id, handoff_id), raw_return)

    verify_key = hashlib.sha256(f"{idempotency_key}:mission-execute-verify"
                                .encode()).hexdigest()[:32]
    verify_result = _classify_execution(task_dir, root_task_id, mission_id, handoff_id, packet,
                                        None, detail, verify_key, "blocked")
    result = {
        "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
        "executor_client": packet.get("executor_client"),
        "invoked": False, "returncode": None, "timed_out": False,
        "raw_return_path": str(raw_return_path(task_dir, mission_id, handoff_id)),
        "classification": "BLOCKED",
        "result_path": verify_result["result_path"],
        "verification_path": verify_result["verification_path"],
        "created_at": iso(now_utc()),
        "coordination_stage": stage,
        "coordination_detail": detail,
    }
    if lease_info is not None:
        result["lease"] = lease_info
    if claim_info is not None:
        result["claim"] = claim_info
    if cleanup is not None:
        result["cleanup"] = cleanup
    idempotency_store(idem_root, idempotency_key, "mission_execute", idem_target, result)
    return dict(result, replay=False)


def mission_execute(task_dir, root_task_id, mission_id, handoff_id, executor_client,
                    executor_session, invocation_id, idempotency_key):
    """Load one existing handoff, revalidate it from scratch against the CURRENT contract and
    state (never trusted from handoff-creation time), resolve its executor through the
    existing, never-bypassed transport-verification gate (`mission_route`), invoke exactly one
    bounded foreground subprocess built entirely from existing helpers
    (`mission_pilot_transport_argv`/`build_mission_pilot_argv`), and convert whatever the
    executor returned into the existing S4 result/verification contract by calling
    `mission_verify` directly — never a second classifier. Idempotent: the same request
    replays its original (already-executed) result without a second subprocess call, and
    without a second lease/claim acquisition; the same key against a materially different
    request refuses as a conflicting replay. Never approves, never expands scope/tools/
    identity, never selects a different client or ticket, never retries, never runs in the
    background.

    T-051-S7-R1: before any subprocess call, acquires exactly one T-050 ticket lease and
    exactly one T-050 file claim on this handoff's own exact approved scope, through the
    existing, unmodified `cli/atlas_coordination.py` library (never a duplicated lease/claim
    implementation here) — using the mission executor's own exact client/session/invocation
    identity. A lease or claim failure stops before any subprocess call and classifies the
    attempt BLOCKED; a claim failure releases the lease this attempt itself just acquired.
    After execution (success or failure), the claim is released first and the lease second,
    always attempted, never retried; a cleanup failure is always surfaced, never hidden, and
    forces this command's own reported classification to BLOCKED even when the underlying
    verifier classification was PASS."""
    idempotency_key = require_identity(idempotency_key, "idempotency-key")
    executor_client = require_identity(executor_client, "executor-client")
    executor_session = require_identity(executor_session, "executor-session")
    invocation_id = require_identity(invocation_id, "invocation-id")
    if not handoff_id or not IDENTITY.fullmatch(str(handoff_id)):
        refuse(f"not a handoff id: {handoff_id!r}")
    handoff_id = str(handoff_id)

    contract, _state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id:
        refuse(f"mission {mission_id!r} belongs to root ticket "
               f"{contract.get('root_task_id')!r}, not {root_task_id!r}", code=4)

    idem_target = (f"{mission_id}::execute::{handoff_id}::{executor_client}::"
                  f"{executor_session}::{invocation_id}")

    with _guard(handoff_dir(task_dir, mission_id, handoff_id) / ".execute.lock",
               "mission-execute"):
        idem_root = execute_idem_dir(task_dir, mission_id, handoff_id)
        cached = idempotency_check(idem_root, idempotency_key, "mission_execute", idem_target)
        if cached is not None:
            return dict(cached, replay=True)

        # Re-read fresh under the guard, mirroring every other mutator's own convention.
        contract, state = load_mission(task_dir, mission_id)
        current_state = state.get("state")
        if current_state in TERMINAL_STATES:
            refuse(f"mission {mission_id!r} is closed (state={current_state!r}) — a closed "
                   f"mission accepts no execution", code=5)
        if current_state != "approved" or state.get("approval") != "recorded":
            refuse(f"mission {mission_id!r} is in state {current_state!r} / approval "
                   f"{state.get('approval')!r} — execution requires an approved mission",
                   code=5)
        if state.get("approval_scope_hash") != _scope_hash(contract):
            refuse(f"mission {mission_id!r} approval_scope_hash no longer matches the "
                   f"contract's current scopes — approval evidence is stale, refusing "
                   f"execution", code=5)

        ttl_seconds = contract.get("ttl_seconds")
        approved_at_raw = state.get("approved_at")
        if approved_at_raw and isinstance(ttl_seconds, int):
            try:
                approved_at_dt = datetime.datetime.fromisoformat(approved_at_raw)
            except ValueError:
                approved_at_dt = None
            if approved_at_dt is not None:
                elapsed = (now_utc() - approved_at_dt).total_seconds()
                if elapsed > ttl_seconds:
                    refuse(f"mission {mission_id!r} ttl_seconds ({ttl_seconds}) elapsed "
                           f"{elapsed:.0f}s after approval — ttl expired, refusing "
                           f"execution", code=5)

        hd = handoff_dir(task_dir, mission_id, handoff_id)
        packet, corrupt = _read_json(hd / "packet.json")
        if packet is None:
            refuse(f"no handoff {handoff_id!r} for mission {mission_id!r}"
                   + (" (corrupt packet.json)" if corrupt else " (no packet.json)"), code=4)
        if packet.get("mission_id") != mission_id or packet.get("handoff_id") != handoff_id:
            refuse(f"handoff {handoff_id!r} packet does not identify itself consistently — "
                   f"identity-mismatched, refusing execution", code=5)

        if (hd / "result.json").is_file() or (hd / "verification.json").is_file():
            refuse(f"handoff {handoff_id!r} already has a recorded result — this handoff was "
                   f"already verified (by a prior `mission execute` or a manual "
                   f"`mission verify`); execution is refused rather than overwriting evidence",
                   code=5)

        # Exact identity match — never a different client, session, or invocation than the
        # one this handoff was actually created for.
        if executor_client != contract.get("executor_client") or \
                executor_client != packet.get("executor_client"):
            refuse(f"--executor-client {executor_client!r} does not exactly match this "
                   f"handoff's own executor_client {packet.get('executor_client')!r} — "
                   f"refusing execution", code=5)
        if executor_session != packet.get("executor_session"):
            refuse(f"--executor-session {executor_session!r} does not match this handoff's "
                   f"own executor_session {packet.get('executor_session')!r} — a session "
                   f"mismatch, refusing execution", code=5)
        if invocation_id != packet.get("invocation_id"):
            refuse(f"--invocation-id {invocation_id!r} does not match this handoff's own "
                   f"invocation_id {packet.get('invocation_id')!r} — an invocation mismatch, "
                   f"refusing execution", code=5)

        # Revalidate the approved scope from scratch — never trusted from handoff-creation
        # time. A scope that no longer canonicalizes safely, or no longer resolves to the
        # exact same file, or is no longer one of the mission's own approved scopes, refuses.
        scope = packet.get("scope") or {}
        try:
            rechecked = canonicalize_scope(scope.get("raw"))
        except MissionError as e:
            refuse(f"this handoff's own scope no longer validates: {e}", code=5)
        if rechecked.get("canonical") != scope.get("canonical"):
            refuse(f"this handoff's own scope now canonicalizes differently than it did at "
                   f"handoff time ({rechecked.get('canonical')} vs {scope.get('canonical')}) "
                   f"— refusing execution rather than trusting a changed path", code=5)
        _require_exact_scope(contract, scope.get("raw"))

        # Tools are never expanded: the handoff's own recorded tool boundary must still
        # exactly match the contract's CURRENT allowed/denied tools.
        if list(contract.get("allowed_tools", [])) != list(packet.get("allowed_tools") or []) \
                or list(contract.get("denied_tools", [])) != list(packet.get("denied_tools")
                                                                  or []):
            refuse(f"mission {mission_id!r}'s allowed_tools/denied_tools no longer match this "
                   f"handoff's own packet — a tool boundary may never be widened between "
                   f"handoff and execution, refusing", code=5)

        # Mission-level limits, revalidated from the CURRENT state — never trusted from
        # whatever they were when this handoff was created.
        attempts_used = int(state.get("attempts_used") or 0)
        max_attempts = contract.get("max_attempts")
        if isinstance(max_attempts, int) and attempts_used > max_attempts:
            refuse(f"mission {mission_id!r} attempts_used ({attempts_used}) exceeds "
                   f"max_attempts ({max_attempts}) — a mission limit was violated, refusing "
                   f"execution", code=5)
        handoffs_so_far = state.get("handoffs") or []
        distinct_scopes = {h.get("scope_canonical") for h in handoffs_so_far
                           if h.get("scope_canonical")}
        max_slices = contract.get("max_slices")
        if isinstance(max_slices, int) and len(distinct_scopes) > max_slices:
            refuse(f"mission {mission_id!r} has used {len(distinct_scopes)} distinct scopes, "
                   f"exceeding max_slices ({max_slices}) — a mission limit was violated, "
                   f"refusing execution", code=5)
        budget_usd = contract.get("budget_usd")
        budget_committed = float(state.get("budget_committed_usd") or 0.0)
        if budget_committed > budget_usd + 1e-9:
            refuse(f"mission {mission_id!r} budget_committed_usd ({budget_committed}) exceeds "
                   f"budget_usd ({budget_usd}) — a mission limit was violated, refusing "
                   f"execution", code=5)

        # Resolve the executor's transport through the existing, never-bypassed routing gate.
        # `mission_route` itself refuses a missing adapter, a missing transport, an
        # adapter/transport identity conflict, and — the check this command most depends on —
        # any transport not marked `verified: true`. Nothing in this command ever calls
        # `resolve_transport`/`mission_pilot_transport_argv` in a way that skips this gate.
        try:
            executor_resolved = mission_route(task_dir, root_task_id, mission_id, "executor")
        except MissionError as e:
            refuse(f"executor role does not route cleanly — refusing execution before any "
                   f"subprocess call: {e}", code=5)
        client = executor_resolved["client"]
        if client != executor_client:
            refuse(f"--executor-client {executor_client!r} does not match the mission's "
                   f"routed executor {client!r} — refusing execution", code=5)
        if not executor_resolved["transport_verified"]:
            refuse(f"the {client!r} transport is declared but not verified (verified: false) "
                   f"— refusing execution before any subprocess call", code=5)

        # Build the argv entirely through the existing, unmodified helpers — no arbitrary
        # argv templating is introduced here, and no second transport registry is consulted.
        try:
            argv = mission_pilot_transport_argv(task_dir, mission_id, handoff_id, client=client)
        except MissionError as e:
            refuse(f"could not build a bounded argv for this execution: {e}", code=5)

        hoff = _load_sibling("atlas-handoff")
        transports = hoff.load_transports()
        spec = transports.get(client) or {}
        timeout = spec.get("timeout")
        if not isinstance(timeout, int) or timeout <= 0:
            timeout = 300

        # --- T-051-S7-R1: acquire exactly one T-050 ticket lease and exactly one T-050 file
        # claim on this handoff's own exact approved scope, through the existing, unmodified
        # `cli/atlas_coordination.py` library — never a duplicated lease/claim implementation
        # inside this module — using the exact mission executor client/session/invocation
        # identity already fully validated above. Both must succeed before any subprocess
        # call; a real Claude CLI invocation is reachable only after this point. -------------
        coord = _coord()
        lease_ttl_seconds = timeout + LEASE_TTL_BUFFER_SECONDS
        lease_idem = _execute_sub_key(idempotency_key, f"lease:{handoff_id}")
        try:
            lease = coord.lease_acquire(task_dir, root_task_id, executor_client,
                                        executor_session, invocation_id, lease_ttl_seconds,
                                        lease_idem)
        except coord.CoordinationError as e:
            return _execute_coordination_failure(
                task_dir, root_task_id, mission_id, handoff_id, packet, "lease_acquire",
                str(e), idem_root, idempotency_key, idem_target)

        claim_idem = _execute_sub_key(idempotency_key, f"claim:{handoff_id}")
        try:
            claim = coord.claim_acquire(task_dir, root_task_id, lease["lease_id"],
                                        scope.get("raw"), executor_client, executor_session,
                                        claim_idem)
        except coord.CoordinationError as e:
            lease_cleanup_idem = _execute_sub_key(idempotency_key,
                                                  f"lease-cleanup:{handoff_id}")
            cleanup = {"lease_released": False}
            try:
                coord.lease_release(task_dir, root_task_id, lease["lease_id"], executor_client,
                                    executor_session, invocation_id, lease_cleanup_idem)
                cleanup["lease_released"] = True
            except coord.CoordinationError as e2:
                cleanup["lease_release_error"] = str(e2)
            return _execute_coordination_failure(
                task_dir, root_task_id, mission_id, handoff_id, packet, "claim_acquire",
                str(e), idem_root, idempotency_key, idem_target,
                lease_info={"lease_id": lease["lease_id"]}, cleanup=cleanup)
        # -------------------------------------------------------------------------------------

        stdin_text = MISSION_EXECUTE_PROMPT_TEMPLATE.format(
            packet_json=json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True))

        started_at = iso(now_utc())
        started_monotonic = time.monotonic()
        # The actual `subprocess.run` call lives in `cli/atlas-handoff.run_transport_subprocess`
        # — not inline here — so that atlas_mission.py itself keeps making exactly the one
        # subprocess call every prior T-051 slice's own frozen test already asserts it makes
        # (to `atlas-paths`, for ticket resolution). This is the module's own established
        # "independent copy, reused via _load_sibling" convention applied to a shared
        # subprocess-invocation helper instead of a shared classifier or gate list.
        returncode, stdout, stderr, timed_out, error_detail = hoff.run_transport_subprocess(
            argv, stdin_text, timeout)
        finished_at = iso(now_utc())
        duration_seconds = round(time.monotonic() - started_monotonic, 3)

        raw_return = {
            "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
            "executor_client": client, "started_at": started_at, "finished_at": finished_at,
            "duration_seconds": duration_seconds, "argv": argv, "timeout_seconds": timeout,
            "returncode": returncode, "timed_out": timed_out, "error_detail": error_detail,
            "stdout": stdout[:MAX_EXECUTOR_OUTPUT_BYTES], "stderr": stderr[:MAX_EXECUTOR_OUTPUT_BYTES],
            "single_foreground_call": True, "no_retry": True, "no_shell": True,
        }
        _atomic_write_json(raw_return_path(task_dir, mission_id, handoff_id), raw_return)

        if timed_out:
            candidate_content, malformed_reason, fallback_status = None, error_detail, "blocked"
        elif error_detail is not None:
            candidate_content, malformed_reason, fallback_status = None, error_detail, "failed"
        elif returncode != 0:
            candidate_content = None
            malformed_reason = f"executor exited {returncode}: {stderr.strip()[:500] or '(no stderr)'}"
            fallback_status = "failed"
        else:
            candidate_content, malformed_reason = _parse_executor_reply(stdout)
            fallback_status = "failed"

        # Deterministic per this exact execute request — never reused across a different
        # request, and never causing mission_verify's own idempotency to collide with a
        # manual `mission verify` call keyed differently.
        verify_key = hashlib.sha256(f"{idempotency_key}:mission-execute-verify"
                                    .encode()).hexdigest()[:32]
        verify_result = _classify_execution(
            task_dir, root_task_id, mission_id, handoff_id, packet, candidate_content,
            malformed_reason, verify_key, fallback_status)

        # --- T-051-S7-R1: release the file claim first, then the ticket lease, in that exact
        # order, regardless of the execution/verification outcome above (timeout, non-zero
        # exit, malformed output, or a real verifier classification all reach this same
        # cleanup). Both releases are always attempted — a failure at the first never skips
        # the second. Neither release is ever retried; a release failure is never hidden, and
        # it always forces the classification this command reports to BLOCKED (the persisted
        # verification.json's own classification is untouched — this only affects what
        # mission_execute itself reports and stores), naming exactly which lease/claim record
        # remains for an owner to inspect. ---------------------------------------------------
        claim_release_idem = _execute_sub_key(idempotency_key, f"claim-release:{handoff_id}")
        cleanup = {"claim_released": False, "lease_released": False}
        try:
            coord.claim_release(task_dir, root_task_id, lease["lease_id"], scope.get("raw"),
                                executor_client, executor_session, claim_release_idem)
            cleanup["claim_released"] = True
        except coord.CoordinationError as e:
            cleanup["claim_release_error"] = str(e)

        lease_release_idem = _execute_sub_key(idempotency_key, f"lease-release:{handoff_id}")
        try:
            coord.lease_release(task_dir, root_task_id, lease["lease_id"], executor_client,
                                executor_session, invocation_id, lease_release_idem)
            cleanup["lease_released"] = True
        except coord.CoordinationError as e:
            cleanup["lease_release_error"] = str(e)

        cleanup_complete = cleanup["claim_released"] and cleanup["lease_released"]
        # -------------------------------------------------------------------------------------

        result = {
            "mission_id": mission_id, "root_task_id": root_task_id, "handoff_id": handoff_id,
            "executor_client": client, "invoked": True,
            "returncode": returncode, "timed_out": timed_out,
            "raw_return_path": str(raw_return_path(task_dir, mission_id, handoff_id)),
            "classification": verify_result["classification"] if cleanup_complete else "BLOCKED",
            "verifier_classification": verify_result["classification"],
            "result_path": verify_result["result_path"],
            "verification_path": verify_result["verification_path"],
            "created_at": finished_at,
            "lease_id": lease["lease_id"],
            "claim_path": claim["path"],
            "cleanup": cleanup,
            "cleanup_complete": cleanup_complete,
        }
        idempotency_store(idem_root, idempotency_key, "mission_execute", idem_target, result)
        return dict(result, replay=False)


def mission_run(task_dir, root_task_id, mission_id, executor_session, invocation_prefix,
                idempotency_key):
    """Run the persisted plan in bounded foreground slices until PASS or a real stop."""
    require_identity(executor_session, "executor-session")
    require_identity(invocation_prefix, "invocation-prefix")
    require_identity(idempotency_key, "idempotency-key")
    contract, state = load_mission(task_dir, mission_id)
    if contract.get("root_task_id") != root_task_id or state.get("state") != "approved":
        refuse("mission run requires an approved mission bound to this root ticket", code=5)
    plan, corrupt = _read_json(mission_dir(task_dir, mission_id) / "plan.json")
    if plan is None:
        refuse("mission has no readable plan.json — run mission plan first", code=5)
    if plan.get("mission_id") != mission_id or plan.get("root_task_id") != root_task_id:
        refuse("mission plan identity does not match the current mission", code=5)
    validated_plan = _validate_plan(contract, plan.get("plan") or {})
    steps = validated_plan["steps"]
    target = f"{mission_id}::run::{executor_session}::{invocation_prefix}"
    cached = idempotency_check(mission_dir(task_dir, mission_id), idempotency_key,
                               "mission_run", target)
    if cached is not None:
        return dict(cached, replay=True)
    slice_budget = float(contract.get("budget_usd", 0.0)) / len(steps)
    handoff = None
    executions = []
    for index, step in enumerate(steps, 1):
        invocation_id = f"{invocation_prefix}-{index}"
        if handoff is None:
            handoff = mission_handoff(
                task_dir, root_task_id, mission_id, step["scope"],
                contract["executor_client"], executor_session, invocation_id,
                "execute", slice_budget, f"{idempotency_key}-handoff-{index}",
                step["objective"])
        else:
            handoff = mission_continue(
                task_dir, root_task_id, mission_id, handoff["handoff_id"], step["scope"],
                contract["executor_client"], executor_session, invocation_id,
                "execute", slice_budget, f"{idempotency_key}-continue-{index}",
                step["objective"])
        execution = mission_execute(
            task_dir, root_task_id, mission_id, handoff["handoff_id"],
            contract["executor_client"], executor_session, invocation_id,
            f"{idempotency_key}-execute-{index}")
        executions.append(execution)
        if execution.get("classification") != "PASS":
            final = mission_finalize(
                task_dir, root_task_id, mission_id, handoff["handoff_id"],
                f"{idempotency_key}-finalize-{index}")
            result = {"mission_id": mission_id, "root_task_id": root_task_id,
                      "executions": executions, "final": final, "replay": False}
            idempotency_store(mission_dir(task_dir, mission_id), idempotency_key,
                              "mission_run", target, result)
            return result
    final = mission_finalize(
        task_dir, root_task_id, mission_id, handoff["handoff_id"],
        f"{idempotency_key}-finalize-final")
    result = {"mission_id": mission_id, "root_task_id": root_task_id,
              "executions": executions, "final": final, "replay": False}
    idempotency_store(mission_dir(task_dir, mission_id), idempotency_key,
                      "mission_run", target, result)
    return result
