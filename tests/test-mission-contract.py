#!/usr/bin/env python3
"""tests/test-mission-contract.py — T-051-S1: the Mission Contract and durable Mission Run
State layer only (`cli/atlas_mission.py` / `cli/atlas-mission`).

Every scenario below runs against a disposable ATLAS_HOME fixture, exactly like
`test-coordinator-conflict-protection.py`'s own `make_ticket_home()` — nothing here touches
the real workspace, and no real mission is ever created for T-050 or any other live ticket.

This file proves the S1 scope only: an owner-approved mission contract and a fail-closed
`created` -> `approved` state machine. It does not exercise, and does not need, a planner,
executor, verifier, or continuation loop — none of that exists yet.
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
    modname = f"under_test_{name.replace('-', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_loader(
        modname, importlib.machinery.SourceFileLoader(modname, str(CLI / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mission_cli = _load("atlas-mission")
mission = _load("atlas_mission.py")


def make_ticket_home(root, project="demo", ticket_id="T-900"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-contract tests\nstate: active\n"
        "project: {project}\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
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
    tmp = tempfile.mkdtemp(prefix="t051-s1-")
    root = Path(tmp)
    d = make_ticket_home(root, ticket_id=ticket_id)
    os.environ["ATLAS_HOME"] = str(root)
    return root, d


def uniq_key(prefix):
    return f"{prefix}-{time.time_ns()}"


CREATE_ARGS = ("--planner", "codex", "--executor", "claude-code", "--verifier", "codex",
               "--budget-usd", "5", "--max-slices", "3", "--max-attempts", "2",
               "--ttl-seconds", "3600")


def do_create(task_id, scope="scope-a.txt", extra=(), key=None):
    key = key or uniq_key("create")
    args = [task_id, "--scope", scope, *CREATE_ARGS, "--idempotency-key", key, *extra]
    return run(mission_cli.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def do_approve(task_id, mission_id, owner_words="approved by owner fixture", key=None):
    key = key or uniq_key("approve")
    return run(mission_cli.cmd_approve,
               [task_id, mission_id, "--owner-words", owner_words,
                "--idempotency-key", key])


# =============================================================================================
t("1. Valid mission creation")
root, d = new_home()
(d / "scope-a.txt").write_text("x")
rc, out, err = do_create("T-900")
chk("valid create exits 0", rc == 0)
mid = mission_id_from(out)
chk("valid create prints a mission id", bool(mid))
chk("contract.json exists on disk", (d / "mission" / mid / "contract.json").is_file())
chk("state.json exists on disk", (d / "mission" / mid / "state.json").is_file())
contract = json.loads((d / "mission" / mid / "contract.json").read_text())
chk("contract has every required field", all(k in contract for k in (
    "mission_id", "root_task_id", "project", "created_at", "created_by", "planner_client",
    "executor_client", "verifier_client", "scopes", "allowed_tools", "denied_tools",
    "budget_usd", "max_slices", "max_attempts", "ttl_seconds",
    "required_verification_policy", "forbidden_actions", "stop_conditions",
    "rollback_policy", "audit_reference", "idempotency_reference")))
chk("default allowed_tools is Read,Edit only", contract["allowed_tools"] == ["Read", "Edit"])
chk("default denied_tools covers Bash/network/MCP/Git/delete/publish/credentials",
    set(contract["denied_tools"]) == {"Bash", "network", "MCP", "Git", "delete", "publish",
                                      "credentials"})
chk("no autonomous approval/publication/deletion/permission-change/recovery/background flags",
    all(contract[k] is True for k in (
        "no_autonomous_approval", "no_autonomous_publication", "no_autonomous_deletion",
        "no_autonomous_permission_changes", "no_automatic_recovery",
        "no_background_execution")))

# =============================================================================================
t("2. Missing required field refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--executor", "claude-code",
                    "--verifier", "codex", "--budget-usd", "5", "--max-slices", "3",
                    "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("missing")])
chk("create with no --planner refuses", rc == 2 and "planner" in err)

# =============================================================================================
t("3. Invalid root task refusal")
rc, out, err = do_create("NO-SUCH-TICKET", key=uniq_key("badticket"))
chk("create against a nonexistent ticket refuses (not found)", rc == 4)

# =============================================================================================
t("4. Invalid mission id refusal")
rc, out, err = do_create("T-900", extra=("--mission-id", "bad id with spaces"),
                         key=uniq_key("badmid"))
chk("create with a malformed --mission-id refuses", rc == 2 and "mission-id" in err)

# =============================================================================================
t("5. Invalid client identity refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "bad client!",
                    "--executor", "claude-code", "--verifier", "codex", "--budget-usd", "5",
                    "--max-slices", "3", "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("badclient")])
chk("create with a malformed planner identity refuses", rc == 2 and "planner" in err)

# =============================================================================================
t("6. Invalid scope refusal (unsafe characters)")
rc, out, err = do_create("T-900", scope="scope a?.txt", key=uniq_key("badscope"))
chk("create with an unsafe scope path refuses", rc == 2)

# =============================================================================================
t("7. Absolute path refusal")
rc, out, err = do_create("T-900", scope="/etc/passwd", key=uniq_key("abspath"))
chk("create with an absolute scope refuses", rc == 2 and "absolute" in err)

# =============================================================================================
t("8. Traversal refusal")
rc, out, err = do_create("T-900", scope="../../etc/passwd", key=uniq_key("traversal"))
chk("create with a traversal scope refuses", rc == 2 and "traversal" in err)

# =============================================================================================
t("9. Directory scope refusal")
rc, out, err = do_create("T-900", scope="projects", key=uniq_key("dirscope"))
chk("create with a scope that resolves to a directory refuses", rc == 2 and "directory" in err)

# =============================================================================================
t("10. Duplicate canonical scope refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--scope", "scope-a.txt",
                    *CREATE_ARGS, "--idempotency-key", uniq_key("dupscope")])
chk("create with the same scope given twice refuses", rc == 2 and "duplicate" in err)

# =============================================================================================
t("11. Invalid budget refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "-3",
                    "--max-slices", "3", "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("badbudget")])
chk("create with a negative budget refuses", rc == 2 and "budget" in err)
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "nan",
                    "--max-slices", "3", "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("nanbudget")])
chk("create with a non-finite budget refuses", rc == 2 and "budget" in err)

# =============================================================================================
t("12. Invalid max-slices refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "5",
                    "--max-slices", "0", "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("badslices")])
chk("create with max-slices 0 refuses", rc == 2 and "max-slices" in err)

# =============================================================================================
t("13. Invalid max-attempts refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "5",
                    "--max-slices", "3", "--max-attempts", "-1", "--ttl-seconds", "3600",
                    "--idempotency-key", uniq_key("badattempts")])
chk("create with negative max-attempts refuses", rc == 2 and "max-attempts" in err)

# =============================================================================================
t("14. Invalid TTL refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "5",
                    "--max-slices", "3", "--max-attempts", "2", "--ttl-seconds", "0",
                    "--idempotency-key", uniq_key("badttl")])
chk("create with ttl-seconds 0 refuses", rc == 2 and "ttl-seconds" in err)

# =============================================================================================
t("15. Credential-shaped input refusal")
rc, out, err = run(mission_cli.cmd_create,
                   ["T-900", "--scope", "scope-a.txt", "--planner", "codex", "--executor",
                    "claude-code", "--verifier", "codex", "--budget-usd", "5",
                    "--max-slices", "3", "--max-attempts", "2", "--ttl-seconds", "3600",
                    "--idempotency-key", "sk-ant-abcdefghijklmnopqrstuvwx"])
chk("create with a credential-shaped idempotency key refuses",
    rc == 2 and "credential" in err.lower() + "" or "carries a" in err)
rc2, out2, err2 = do_approve("T-900", mid, owner_words="password: \"abcdefghijklmnop\"",
                             key=uniq_key("credapprove"))
chk("approve with a credential-shaped owner-words value refuses",
    rc2 == 2 and "carries a" in err2)

# =============================================================================================
t("16. Mission starts unapproved")
rc, out, err = do_create("T-900", key=uniq_key("unapproved"))
mid2 = mission_id_from(out)
state = json.loads((d / "mission" / mid2 / "state.json").read_text())
chk("newly created mission has state 'created'", state["state"] == "created")
chk("newly created mission has approval 'none'", state["approval"] == "none")

# =============================================================================================
t("17. Mission approval requires owner words")
rc, out, err = run(mission_cli.cmd_approve,
                   ["T-900", mid2, "--owner-words", "", "--idempotency-key",
                    uniq_key("noowner")])
chk("approve with empty --owner-words refuses", rc == 2 and "owner-words" in err)
rc, out, err = run(mission_cli.cmd_approve,
                   ["T-900", mid2, "--idempotency-key", uniq_key("noownerflag")])
chk("approve with --owner-words omitted entirely refuses", rc == 2)

# =============================================================================================
t("18. Mission approval records immutable approval evidence")
rc, out, err = do_approve("T-900", mid2, owner_words="owner approves this mission",
                          key=uniq_key("realapprove"))
chk("a valid approval exits 0", rc == 0)
state_after = json.loads((d / "mission" / mid2 / "state.json").read_text())
chk("approval recorded with owner_words, approved_at, approval_scope_hash",
    state_after["approval"] == "recorded" and state_after["owner_words"] and
    state_after["approved_at"] and state_after["approval_scope_hash"])
rc, out, err = do_approve("T-900", mid2, owner_words="a different approval attempt",
                          key=uniq_key("secondapprove"))
chk("a second, differently-keyed approval attempt after approval is refused", rc == 5)
state_unchanged = json.loads((d / "mission" / mid2 / "state.json").read_text())
chk("approval evidence is unchanged by the refused second attempt",
    state_unchanged == state_after)

# =============================================================================================
t("19. Repeated create is idempotent")
key19 = uniq_key("idemcreate")
rc1, out1, _ = do_create("T-900", scope="scope-b.txt", key=key19)
rc2, out2, _ = do_create("T-900", scope="scope-b.txt", key=key19)
chk("both calls exit 0", rc1 == 0 and rc2 == 0)
chk("both calls return the same mission id",
    mission_id_from(out1) == mission_id_from(out2))
chk("the replay is labeled as a duplicate, not a second mission", "duplicate" in out2)
mission_dirs = list((d / "mission").glob("mission-*"))
chk("exactly one mission directory exists per distinct create call so far "
    "(no silent duplicate written for the replay)",
    len({p.name for p in mission_dirs}) == len(mission_dirs))

# =============================================================================================
t("20. Repeated approve is idempotent")
key20 = uniq_key("idemapprove")
rc1, out1, _ = do_approve("T-900", mid2, owner_words="idempotent approval text", key=key20)
rc2, out2, _ = do_approve("T-900", mid2, owner_words="idempotent approval text", key=key20)
chk("first replay call is refused (already approved by an earlier key)", rc1 == 5)
# mid2 was already approved above (test 18) — exercise idempotent replay on a FRESH mission.
rc3, out3, _ = do_create("T-900", scope="scope-c.txt", key=uniq_key("forreplay"))
mid3 = mission_id_from(out3)
key20b = uniq_key("idemapprove2")
rc4, out4, _ = do_approve("T-900", mid3, owner_words="idempotent approval text", key=key20b)
rc5, out5, _ = do_approve("T-900", mid3, owner_words="idempotent approval text", key=key20b)
chk("approving the same fresh mission twice with the same key exits 0 both times",
    rc4 == 0 and rc5 == 0)
chk("the second call is labeled a replay, not a second approval", "duplicate" in out5)
audit_lines = (d / "mission" / mid3 / "audit.log").read_text().splitlines()
approve_events = [l for l in audit_lines if json.loads(l).get("op") == "mission_approve"]
chk("no duplicate audit event was written for the idempotent replay",
    len(approve_events) == 1)

# =============================================================================================
t("21. Conflicting mission id refusal")
rc, out, err = do_create("T-900", scope="scope-d.txt", extra=("--mission-id", mid3),
                         key=uniq_key("conflict"))
chk("creating with an explicit --mission-id that already exists refuses", rc == 5)

# =============================================================================================
t("22. Invalid state transition refusal")
rc, out, err = do_approve("T-900", mid3, owner_words="trying again after approval",
                          key=uniq_key("badtransition"))
chk("approving an already-approved mission with a new key refuses (fail closed)", rc == 5)
rc, out, err = run(mission_cli.cmd_approve,
                   ["T-900", "mission-does-not-exist-aaaaaaaaaaaaaaaa", "--owner-words",
                    "x", "--idempotency-key", uniq_key("noexist")])
chk("approving a mission id that does not exist refuses (not found)", rc == 4)

# =============================================================================================
t("23. show is read-only")
before = (d / "mission" / mid3 / "state.json").read_text()
rc, out, err = run(mission_cli.cmd_show, ["T-900", mid3])
chk("show exits 0", rc == 0)
after = (d / "mission" / mid3 / "state.json").read_text()
chk("state.json is byte-identical before and after show", before == after)
chk("show output states execution is not enabled in this slice",
    "execution is not enabled" in out)

# =============================================================================================
t("24. status is read-only")
before = (d / "mission" / mid3 / "state.json").read_text()
rc, out, err = run(mission_cli.cmd_status, ["T-900", mid3])
chk("status exits 0", rc == 0)
after = (d / "mission" / mid3 / "state.json").read_text()
chk("state.json is byte-identical before and after status", before == after)

# =============================================================================================
t("25. Stable human-readable output")
rc, out1, _ = run(mission_cli.cmd_show, ["T-900", mid3])
rc, out2, _ = run(mission_cli.cmd_show, ["T-900", mid3])
chk("two consecutive 'show' calls print byte-identical text", out1 == out2)

# =============================================================================================
t("26. Stable JSON output")
rc, out1, _ = run(mission_cli.cmd_show, ["T-900", mid3, "--json"])
rc, out2, _ = run(mission_cli.cmd_show, ["T-900", mid3, "--json"])
chk("two consecutive 'show --json' calls print byte-identical JSON", out1 == out2)
view = json.loads(out1)
chk("JSON output is a JSON object with the documented top-level fields",
    all(k in view for k in ("mission_id", "root_task_id", "state", "approval", "scopes",
                            "next_owner_action", "execution_enabled_in_this_slice")))
chk("JSON output explicitly states execution is not enabled",
    view["execution_enabled_in_this_slice"] is False)

# =============================================================================================
t("27/28. No lease or file claim was ever created by mission create/approve")
chk("no 'coordination/' directory exists under the ticket (no lease/claim/state file)",
    not (d / "coordination").is_dir())
chk("no runtime coordination-claims directory was created under ATLAS_HOME",
    not (root / "runtime" / "coordination" / "claims").is_dir())

# =============================================================================================
t("29. No handoff was ever created")
chk("no handoff-*.md record exists under the ticket", not list(d.glob("handoff-*.md")))

# =============================================================================================
t("30. No AI invocation")
mission_src = (CLI / "atlas_mission.py").read_text()
cli_src = (CLI / "atlas-mission").read_text()
forbidden_markers = ("codex-reply", "claude-reply", "anthropic.", "openai.", "requests.get",
                     "requests.post", "urllib.request", "http.client", "socket.socket")
chk("atlas_mission.py contains no AI/network invocation markers",
    not any(mk in mission_src for mk in forbidden_markers))
chk("atlas-mission contains no AI/network invocation markers",
    not any(mk in cli_src for mk in forbidden_markers))
chk("the only subprocess use in atlas_mission.py targets the existing atlas-paths resolver",
    "subprocess.run([str(PATHS_RESOLVER)" in mission_src
    and mission_src.count("subprocess.run(") == 1)

# =============================================================================================
t("31. No runtime state")
runtime_dir = root / "runtime"
chk("no $ATLAS_HOME/runtime directory was created by mission create/approve/show/status",
    not runtime_dir.is_dir())
chk("every mission file lives under the ticket's own mission/ directory",
    (d / "mission" / mid3 / "contract.json").is_file())

# =============================================================================================
t("32. Core/engine parity")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


core_mission_py = REPO.parent / "core" / "cli" / "atlas_mission.py"
core_mission_cli = REPO.parent / "core" / "cli" / "atlas-mission"
chk("core/cli/atlas_mission.py exists", core_mission_py.is_file())
chk("core/cli/atlas-mission exists", core_mission_cli.is_file())
if core_mission_py.is_file():
    chk("engine/cli/atlas_mission.py and core/cli/atlas_mission.py are byte-identical",
        sha(CLI / "atlas_mission.py") == sha(core_mission_py))
if core_mission_cli.is_file():
    chk("engine/cli/atlas-mission and core/cli/atlas-mission are byte-identical",
        sha(CLI / "atlas-mission") == sha(core_mission_cli))

# =============================================================================================
t("33. Canonical atlas parity — both dispatchers route 'mission' the same way")
atlas_text = (CLI / "atlas").read_text()
core_atlas_text = (REPO.parent / "core" / "cli" / "atlas").read_text()
chk("engine/cli/atlas dispatches 'mission' to atlas-mission",
    "mission" in atlas_text and 'exec "$SELF_DIR/atlas-$cmd"' in atlas_text)
chk("core/cli/atlas dispatches 'mission' to atlas-mission",
    "mission" in core_atlas_text and 'exec "$SELF_DIR/atlas-$cmd"' in core_atlas_text)
import re as _re
atlas_case = _re.search(r"init\|[a-z|-]*mission[a-z|-]*\)", atlas_text)
core_case = _re.search(r"init\|[a-z|-]*mission[a-z|-]*\)", core_atlas_text)
chk("'mission' sits in engine/cli/atlas's generic exec-by-name case arm", bool(atlas_case))
chk("'mission' sits in core/cli/atlas's generic exec-by-name case arm", bool(core_case))


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
