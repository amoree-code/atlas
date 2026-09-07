#!/usr/bin/env python3
"""tests/test-mission-routing.py — T-051-S2: generic role and capability resolution
(`mission route` / `mission validate`) on top of the T-051-S1 mission contract layer.

Every scenario runs against a disposable ATLAS_HOME, plus a disposable adapter registry
and a disposable transport registry (via AI_OS_ADAPTERS / AI_OS_HANDOFF_TRANSPORTS), exactly
like `test-mission-contract.py`'s own `make_ticket_home()` fixture pattern. Nothing here
reads or writes the real `adapters/`, the real
`internal/governance/policies/handoff-transports.yaml`, or any real mission record.

This file proves the S2 scope only: read-only role/client/adapter/transport/capability
resolution. No planner, executor, or verifier is ever invoked; no lease, claim, or handoff is
ever created; the continuation loop still does not exist.
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
    modname = f"under_test_{cli_dir.parent.name}_{name.replace('-', '_').replace('.', '_')}"
    spec = importlib.util.spec_from_loader(
        modname, importlib.machinery.SourceFileLoader(modname, str(cli_dir / name)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mission_cli = _load(CLI, "ai-os-mission")
mission = _load(CLI, "aios_mission.py")
core_mission_cli = _load(CORE_CLI, "ai-os-mission")
core_mission = _load(CORE_CLI, "aios_mission.py")


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
# Fixture registries: an isolated ATLAS_HOME, an isolated adapters/ tree, an isolated
# transports.yaml. Every entry name is a fixture-only test double — none of these client ids
# exist in the real adapters/ or handoff-transports.yaml.
# =============================================================================================

ADAPTER_YAML = """\
adapter: {client}
name: fixture adapter for {client}
contract: 1

client:
  detect: [/nonexistent]
{version_line}  consumer_verified: false

provides:
{provides}

writes: []
requires: []
enforces: []
"""


def write_adapter(adapters_dir, client, version_cmd=None, provides=None):
    d = adapters_dir / client
    d.mkdir(parents=True, exist_ok=True)
    version_line = f"  version_cmd: {version_cmd}\n" if version_cmd else ""
    if provides:
        provides_body = "\n".join(
            f"  {k}: {{ path: /nonexistent, format: markdown, verified: true }}"
            for k in provides)
    else:
        provides_body = "  {}"
    (d / "adapter.yaml").write_text(ADAPTER_YAML.format(
        client=client, version_line=version_line, provides=provides_body))


TRANSPORT_ENTRY = """\
  {client}:
    name: fixture transport for {client}
    binary: {binary}
    argv: [--tools, "{tools}"]
    stdin: packet
    timeout: 60
    verified: {verified}
    evidence: fixture, not a real trial
"""


def write_transports(path, entries):
    body = "contract: 1\n\ntransports:\n"
    for e in entries:
        body += TRANSPORT_ENTRY.format(**e)
    path.write_text(body)


def new_fixture(ticket_id="T-910"):
    """One disposable ATLAS_HOME + ticket + adapter registry + transport registry.
    Returns (root, task_dir, adapters_dir, transports_path)."""
    tmp = Path(tempfile.mkdtemp(prefix="t051-s2-"))
    d = tmp / "projects" / "demo" / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for mission-routing tests\nstate: active\n"
        "project: demo\nopened_at: 2026-09-07 12:00 PM\nupdated_at: 2026-09-07 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id))

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    transports_path = tmp / "handoff-transports.yaml"

    # Registered clients with both a matching adapter AND a matching, verified transport.
    write_adapter(adapters_dir, "test-planner", version_cmd="test-planner-bin --version",
                  provides=["rules"])
    write_adapter(adapters_dir, "test-executor", version_cmd="test-executor-bin --version",
                  provides=["rules", "skills"])
    write_adapter(adapters_dir, "test-verifier", version_cmd="test-verifier-bin --version",
                  provides=["rules"])
    # Adapter exists, transport declares verified:false.
    write_adapter(adapters_dir, "unverified-client", version_cmd="unverified-bin --version")
    # Adapter exists, no transport entry at all.
    write_adapter(adapters_dir, "no-transport-client", version_cmd="ghost-bin --version")
    # Adapter and transport both exist, but declare DIFFERENT binaries.
    write_adapter(adapters_dir, "contradict-client", version_cmd="contradict-bin --version")
    # A suggestively-named client whose transport does NOT declare the suggested tool.
    write_adapter(adapters_dir, "claude-bash-power-tool",
                  version_cmd="claude-bash-power-tool-bin --version")
    # A client whose transport declares MORE tools than any mission ever allows.
    write_adapter(adapters_dir, "exceed-client", version_cmd="exceed-bin --version")
    # NOTE: intentionally no adapter dir for "no-adapter-client" — missing-adapter fixture.

    write_transports(transports_path, [
        dict(client="test-planner", binary="test-planner-bin", tools="Read,Edit",
             verified="true"),
        dict(client="test-executor", binary="test-executor-bin", tools="Read,Edit",
             verified="true"),
        dict(client="test-verifier", binary="test-verifier-bin", tools="Read,Edit",
             verified="true"),
        dict(client="unverified-client", binary="unverified-bin", tools="Read",
             verified="false"),
        dict(client="contradict-client", binary="totally-different-bin", tools="Read,Edit",
             verified="true"),
        dict(client="no-adapter-client", binary="ghost2-bin", tools="Read,Edit",
             verified="true"),
        dict(client="claude-bash-power-tool", binary="claude-bash-power-tool-bin",
             tools="Read,Edit", verified="true"),
        dict(client="exceed-client", binary="exceed-bin", tools="Read,Edit,Extra",
             verified="true"),
    ])

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["AI_OS_ADAPTERS"] = str(adapters_dir)
    os.environ["AI_OS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp, d, adapters_dir, transports_path


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


DEFAULT_ROLES = {"--planner": "test-planner", "--executor": "test-executor",
                 "--verifier": "test-verifier"}
COMMON_ARGS = ("--budget-usd", "5", "--max-slices", "3", "--max-attempts", "2",
              "--ttl-seconds", "3600")


def do_create(task_id, scope="scope-a.txt", role_overrides=(), key=None, m=None):
    """role_overrides: e.g. ('--executor', 'some-client') replaces the default role client
    instead of appending a duplicate flag."""
    m = m or mission_cli
    key = key or uniq_key("create")
    roles = dict(DEFAULT_ROLES)
    if role_overrides:
        roles[role_overrides[0]] = role_overrides[1]
    role_args = []
    for flag, client in roles.items():
        role_args += [flag, client]
    args = [task_id, "--scope", scope, *role_args, *COMMON_ARGS,
           "--idempotency-key", key]
    return run(m.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def do_approve(task_id, mission_id, owner_words="approved by owner fixture", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("approve")
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words", owner_words,
                               "--idempotency-key", key])


def make_approved_mission(task_id="T-910", extra_create=(), m=None):
    m = m or mission_cli
    rc, out, err = do_create(task_id, role_overrides=extra_create, m=m)
    assert rc == 0, (rc, out, err)
    mid = mission_id_from(out)
    rc, out, err = do_approve(task_id, mid, m=m)
    assert rc == 0, (rc, out, err)
    return mid


def tamper_json(path, mutate_fn):
    obj = json.loads(path.read_text())
    mutate_fn(obj)
    path.write_text(json.dumps(obj, sort_keys=True, indent=2))


# =============================================================================================
t("1-3. route each role to its declared client")
root, d, adapters_dir, transports_path = new_fixture()
(d / "scope-a.txt").write_text("x")
mid = make_approved_mission()

for role, expected_client in (("planner", "test-planner"), ("executor", "test-executor"),
                              ("verifier", "test-verifier")):
    rc, out, err = run(mission_cli.cmd_route, ["T-910", mid, "--role", role, "--json"])
    chk(f"route {role} exits 0", rc == 0)
    view = json.loads(out) if rc == 0 else {}
    chk(f"route {role} selects {expected_client}", view.get("client") == expected_client)
    chk(f"route {role} reports transport_verified true", view.get("transport_verified") is True)
    chk(f"route {role} reports mission_allowed_tools Read/Edit",
        set(view.get("mission_allowed_tools", [])) == {"Read", "Edit"})

# =============================================================================================
t("4. missing/unknown role refusal")
rc, out, err = run(mission_cli.cmd_route, ["T-910", mid, "--role", "reviewer"])
chk("route with an unknown role refuses", rc == 2 and "role" in err)

# =============================================================================================
t("5. unapproved mission refusal")
rc, out, err = do_create("T-910", key=uniq_key("unapproved"))
unapproved_mid = mission_id_from(out)
rc, out, err = run(mission_cli.cmd_route, ["T-910", unapproved_mid, "--role", "executor"])
chk("route against an unapproved mission refuses", rc == 5 and "approved" in err)
rc, out, err = run(mission_cli.cmd_validate, ["T-910", unapproved_mid, "--json"])
chk("validate on an unapproved mission still exits 0 (reports invalid, does not crash)",
    rc == 0)
view = json.loads(out)
chk("validate reports valid: false for an unapproved mission", view["valid"] is False)
chk("validate's role_routing marks every role not-ok when unapproved",
    all(not v["ok"] for v in view["role_routing"].values()))

# =============================================================================================
t("6. missing adapter refusal")
mid6 = make_approved_mission(extra_create=("--executor", "no-adapter-client"))
rc, out, err = run(mission_cli.cmd_route, ["T-910", mid6, "--role", "executor"])
chk("route to a client with no adapter refuses", rc == 4 and "adapter" in err)

# =============================================================================================
t("7. missing transport refusal")
mid7 = make_approved_mission(extra_create=("--executor", "no-transport-client"))
rc, out, err = run(mission_cli.cmd_route, ["T-910", mid7, "--role", "executor"])
chk("route to a client with no transport refuses", rc == 4 and "transport" in err)

# =============================================================================================
t("8. unverified transport refusal")
mid8 = make_approved_mission(extra_create=("--executor", "unverified-client"))
rc, out, err = run(mission_cli.cmd_route, ["T-910", mid8, "--role", "executor"])
chk("route to an unverified transport refuses", rc == 5 and "verified" in err)

# =============================================================================================
t("9. requested capability available")
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid, "--role", "executor", "--capability", "Read", "--json"])
chk("requesting an available capability exits 0", rc == 0)
view = json.loads(out)
chk("capability decision is capability_available", view["capability_decision"] == "capability_available")
chk("requested_capability echoed back", view["requested_capability"] == "Read")

# =============================================================================================
t("10. requested capability unavailable")
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid, "--role", "executor", "--capability", "Git"])
chk("requesting a capability the transport never declares refuses", rc == 5)

# =============================================================================================
t("11. mission denied tool refusal")
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid, "--role", "executor", "--capability", "Bash"])
chk("requesting a mission-denied tool refuses", rc == 5 and "denied_tools" in err)

# =============================================================================================
t("12. transport tool capability cannot exceed mission allowed tools")
mid12 = make_approved_mission(extra_create=("--executor", "exceed-client"))
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid12, "--role", "executor", "--capability", "Extra"])
chk("a capability the transport declares, but the mission does not allow, refuses", rc == 5)
chk("refusal cites the mission's allowed_tools boundary, not the transport's", "allowed_tools" in err)

# =============================================================================================
t("13. client name does not grant capabilities")
mid13 = make_approved_mission(extra_create=("--executor", "claude-bash-power-tool"))
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid13, "--role", "executor", "--capability", "Bash"])
chk("a suggestively-named client gets no capability the transport does not declare",
    rc == 5 and "denied_tools" in err)
rc, out, err = run(mission_cli.cmd_route,
                   ["T-910", mid13, "--role", "executor", "--capability", "Read", "--json"])
chk("the same client still gets its actually-declared capability", rc == 0)

# =============================================================================================
t("14. contradictory adapter/transport identity refusal")
mid14 = make_approved_mission(extra_create=("--executor", "contradict-client"))
rc, out, err = run(mission_cli.cmd_route, ["T-910", mid14, "--role", "executor"])
chk("mismatched adapter/transport binaries refuse", rc == 5 and "contradictory" in err)

# =============================================================================================
t("15. validate approved mission successfully")
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid, "--json"])
chk("validate on the clean approved mission exits 0", rc == 0)
view = json.loads(out)
chk("validate reports valid: true", view["valid"] is True)
chk("validate has no findings", view["findings"] == [])
chk("validate's role_routing resolves all three roles", all(v["ok"] for v in
    view["role_routing"].values()))

# =============================================================================================
t("16. validate malformed mission")
mid16 = make_approved_mission()
contract_path = mission.contract_path(d, mid16)
tamper_json(contract_path, lambda c: c.pop("executor_client"))
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid16, "--json"])
chk("validate on a mission missing executor_client exits 0 (reports, does not crash)", rc == 0)
view = json.loads(out)
chk("validate reports valid: false for a malformed contract", view["valid"] is False)
chk("validate names the missing field in its findings",
    any("executor_client" in f for f in view["findings"]))

# =============================================================================================
t("17. validate invalid approval hash")
mid17 = make_approved_mission()
state_path = mission.state_path(d, mid17)
tamper_json(state_path, lambda s: s.__setitem__("approval_scope_hash", "0" * 64))
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid17, "--json"])
view = json.loads(out)
chk("validate catches a tampered approval_scope_hash", view["valid"] is False)
chk("finding mentions approval_scope_hash", any("approval_scope_hash" in f for f in view["findings"]))

# =============================================================================================
t("18. validate invalid scope")
mid18 = make_approved_mission()
tamper_json(mission.contract_path(d, mid18),
           lambda c: c.__setitem__("scopes", [{"raw": "/etc/passwd", "canonical": "/etc/passwd"}]))
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid18, "--json"])
view = json.loads(out)
chk("validate catches an absolute-path scope", view["valid"] is False)
chk("finding mentions the invalid scope", any("scope" in f for f in view["findings"]))

# =============================================================================================
t("19. validate invalid budget")
mid19 = make_approved_mission()
tamper_json(mission.contract_path(d, mid19), lambda c: c.__setitem__("budget_usd", -5))
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid19, "--json"])
view = json.loads(out)
chk("validate catches a negative budget", view["valid"] is False)
chk("finding mentions budget_usd", any("budget_usd" in f for f in view["findings"]))

# =============================================================================================
t("20. validate invalid role client")
mid20 = make_approved_mission()
tamper_json(mission.contract_path(d, mid20),
           lambda c: c.__setitem__("executor_client", "bad id with spaces"))
rc, out, err = run(mission_cli.cmd_validate, ["T-910", mid20, "--json"])
view = json.loads(out)
chk("validate catches an invalid role client identity", view["valid"] is False)
chk("finding mentions executor_client", any("executor_client" in f for f in view["findings"]))

# =============================================================================================
t("21-23. deterministic human-readable/JSON output, repeated route calls byte-identical")
rc1, out1, err1 = run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor",
                                              "--capability", "Read"])
rc2, out2, err2 = run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor",
                                              "--capability", "Read"])
chk("repeated human-readable route calls are byte-identical", rc1 == rc2 == 0 and out1 == out2)

rc1, j1, _ = run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor",
                                         "--capability", "Read", "--json"])
rc2, j2, _ = run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor",
                                         "--capability", "Read", "--json"])
chk("repeated JSON route calls are byte-identical", rc1 == rc2 == 0 and j1 == j2)
chk("JSON output round-trips through json.loads", json.loads(j1) == json.loads(j2))

# =============================================================================================
t("24-26. route/validate are entirely read-only")
before = snapshot(root)
run(mission_cli.cmd_route, ["T-910", mid, "--role", "planner", "--json"])
run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor", "--capability", "Read",
                           "--json"])
after_route = snapshot(root)
chk("route creates no files", before == after_route)

run(mission_cli.cmd_validate, ["T-910", mid, "--json"])
after_validate = snapshot(root)
chk("validate creates no files", after_route == after_validate)

chk("no coordination/ directory exists anywhere under the fixture root",
    not any(p.name == "coordination" for p in root.rglob("*") if p.is_dir()))
chk("no runtime/ directory exists anywhere under the fixture root",
    not any(p.name == "runtime" for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md record exists anywhere under the fixture root",
    not list(root.rglob("handoff-*.md")))
chk("no claims/ or leases/ directory exists anywhere under the fixture root",
    not any(p.name in ("claims", "leases") for p in root.rglob("*") if p.is_dir()))

# =============================================================================================
t("27. core/engine parity")
mid_core = make_approved_mission(m=core_mission_cli)
rc_e, out_e, _ = run(mission_cli.cmd_route, ["T-910", mid, "--role", "executor",
                                             "--capability", "Read", "--json"])
rc_c, out_c, _ = run(core_mission_cli.cmd_route, ["T-910", mid_core, "--role", "executor",
                                                  "--capability", "Read", "--json"])
view_e, view_c = json.loads(out_e), json.loads(out_c)
same_shape = {k: v for k, v in view_e.items() if k not in ("mission_id",)} == \
             {k: v for k, v in view_c.items() if k not in ("mission_id",)}
chk("engine and core mission route agree on client/adapter/transport/capability shape",
    rc_e == rc_c == 0 and same_shape)

rc_e, out_e, _ = run(mission_cli.cmd_validate, ["T-910", mid, "--json"])
rc_c, out_c, _ = run(core_mission_cli.cmd_validate, ["T-910", mid_core, "--json"])
view_e, view_c = json.loads(out_e), json.loads(out_c)
chk("engine and core mission validate agree on valid/findings shape",
    rc_e == rc_c == 0 and view_e["valid"] == view_c["valid"] == True and
    view_e["findings"] == view_c["findings"] == [])

engine_py = CLI / "aios_mission.py"
core_py = CORE_CLI / "aios_mission.py"
chk("engine/cli/aios_mission.py and core/cli/aios_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "ai-os-mission"
core_cli_file = CORE_CLI / "ai-os-mission"
chk("engine/cli/ai-os-mission and core/cli/ai-os-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())

# =============================================================================================
t("28. canonical atlas parity")
atlas_text = (CLI / "atlas").read_text()
core_ai_os_text = (CORE_CLI / "ai-os").read_text()
chk("'mission' still sits in engine/cli/atlas's generic exec-by-name case arm",
    "|mission|" in atlas_text or "mission|" in atlas_text)
chk("'mission' still sits in core/cli/ai-os's generic exec-by-name case arm",
    "|mission|" in core_ai_os_text or "mission|" in core_ai_os_text)

# A clean environment for the subprocess checks below: this file's own fixtures override
# ATLAS_HOME / AI_OS_ADAPTERS / AI_OS_HANDOFF_TRANSPORTS in-process for the tests above, and
# those must never leak into another suite's subprocess, which expects the real workspace.
_CLEAN_ENV = {k: v for k, v in os.environ.items()
             if k not in ("ATLAS_HOME", "AI_OS_ADAPTERS", "AI_OS_HANDOFF_TRANSPORTS")}

# =============================================================================================
t("29. all T-051-S1 tests remain green")
r = subprocess.run([sys.executable, str(REPO / "tests" / "test-mission-contract.py")],
                   capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-mission-contract.py (T-051-S1) exits 0", r.returncode == 0)
chk("test-mission-contract.py reports zero FAIL lines",
    "FAIL" not in r.stdout and "FAIL" not in r.stderr)

# =============================================================================================
t("30. all T-050 S1-S7 tests remain green")
r1 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-conflict-protection.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-conflict-protection.py exits 0", r1.returncode == 0)
r2 = subprocess.run([sys.executable, str(REPO / "tests" / "test-coordinator-routing.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-coordinator-routing.py exits 0", r2.returncode == 0)
r3 = subprocess.run([sys.executable, str(REPO / "tests" / "test-cli-source-drift.py")],
                    capture_output=True, text=True, env=_CLEAN_ENV)
chk("test-cli-source-drift.py exits 0", r3.returncode == 0)


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
sys.exit(0 if failed == 0 else 1)
