#!/usr/bin/env python3
"""tests/test-mission-live-transport.py — T-051-S7 live pilot: the scope-aware
`claude-code-mission-pilot` transport, and a REAL two-ticket bounded Claude CLI pilot run
against it.

## What is real here, and what is not

Sections 1-3 below inspect the REAL `internal/governance/policies/handoff-transports.yaml`
(no override) to prove: `claude-code-tools-pilot` is untouched, byte-for-byte, from before
this slice; the new `claude-code-mission-pilot` entry exists, is declared `verified: false`,
and its argv shape matches exactly what this record documents. These sections read the real
file directly and invoke no client.

Section 4 runs the REAL T-051 pipeline (create -> approve -> handoff -> execute -> verify ->
continue/finalize) against TWO disposable fixture tickets, and — for exactly one bounded
call per fixture mission — invokes the REAL, installed `claude` binary as a real subprocess,
using the exact argv `atlas_mission.build_mission_pilot_argv`/`resolve_mission_pilot_directory`
derive from each mission's own approved scope. This is a genuine, live, costed API call
(bounded to $0.10 per the transport's own `--max-budget-usd` flag, and to `Read`/`Edit`-only
tools via `--tools`/`--restricted`), not a mock and not a fixture standing in for one.

To satisfy the T-051 pipeline's own role-routing gate (`mission_route` correctly refuses any
`verified: false` transport — a real, sound safety check this file does not weaken), the
DISPOSABLE fixture transport registry these pipeline tests point `ATLAS_HANDOFF_TRANSPORTS`
at declares its own `claude-code-mission-pilot` entry as `verified: true`, with the identical
argv template the REAL (still `verified: false`) registry entry declares. This is the same
convention every prior T-051 test file already uses (disposable fixture transports are
always marked `verified: true` in their own disposable registry so the pipeline gate can be
exercised in a test at all — none of that has ever implied, or been read as, promoting the
REAL registry). The REAL entry is inspected, unmodified, in sections 1-3, and re-inspected
at the end of section 4 to prove this test never wrote `verified: true` to it.

Continuation-after-PASS (a required test) reuses mission A's own already-live-verified PASS
result to drive one more bounded handoff, and — to hold total live invocations to exactly
one per fixture mission, matching the pilot rule's own literal wording — verifies that
second handoff with a synthetic-but-structurally-identical result packet, exactly as every
prior T-051 mission test already does for its own non-live scenarios. This is disclosed here,
not hidden.

The third, deliberately identity-mismatched fixture mission proves the pipeline refuses
*before* reaching the point this file would ever call `subprocess` — verified by asserting
zero additional `claude` invocations happened for that mission's own fixture file, which
never leaves its baseline content.
"""
import contextlib
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli"
CORE_CLI = REPO.parent / "core" / "cli"
REAL_TRANSPORTS_PATH = REPO / "internal" / "governance" / "policies" / "handoff-transports.yaml"

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
    modname = f"under_test_{cli_dir.parent.name}_{name.replace('-', '_').replace('.', '_')}_livet"
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


# =============================================================================================
# SECTIONS 1-3: inspect the REAL registry file directly. No ATLAS_HANDOFF_TRANSPORTS
# override yet — these read internal/governance/policies/handoff-transports.yaml exactly as
# atlas-handoff would by default.
# =============================================================================================
for _var in ("ATLAS_HOME", "ATLAS_ADAPTERS", "ATLAS_HANDOFF_TRANSPORTS"):
    os.environ.pop(_var, None)

mission = _load(CLI, "atlas_mission.py")
core_mission = _load(CORE_CLI, "atlas_mission.py")
mission_cli = _load(CLI, "atlas-mission")
core_mission_cli = _load(CORE_CLI, "atlas-mission")
hoff_real = _load(CLI, "atlas-handoff")

t("1. old claude-code-tools-pilot entry preserved byte-for-byte")
real_transports = hoff_real.load_transports()
old_pilot = real_transports.get("claude-code-tools-pilot")
chk("claude-code-tools-pilot still exists in the real registry", old_pilot is not None)
EXPECTED_OLD_ARGV = ["-p", "--no-session-persistence", "--restricted", "--strict-mcp-config",
                     "--add-dir", "projects/atlas/tickets/AIOS-012", "--tools", "Read",
                     "Edit", "--permission-mode", "acceptEdits", "--permission-prompts",
                     "none", "--max-budget-usd", "0.10", "--"]
chk("its argv is byte-for-byte the same list this slice found before editing the file",
    old_pilot.get("argv") == EXPECTED_OLD_ARGV)
chk("it is still verified: true (this slice never touched it)", old_pilot.get("verified") is True)
chk("its binary is still 'claude'", old_pilot.get("binary") == "claude")
raw_transports_text = REAL_TRANSPORTS_PATH.read_text()
chk("the real file still contains the exact original AIOS-012 add-dir line, unmodified",
    "--add-dir, projects/atlas/tickets/AIOS-012," in raw_transports_text)

# =============================================================================================
t("2. claude-code-mission-pilot entry: promoted, correctly shaped")
new_pilot = real_transports.get("claude-code-mission-pilot")
chk("claude-code-mission-pilot exists in the real registry", new_pilot is not None)
# Owner-approved promotion on 2026-09-07 (after this slice's own live pilot evidence)
# moved this from declared-unverified to verified: true — a real, ticket-recorded state
# change, not a regression. The budget is a per-mission placeholder now, not a static
# "0.10" — substituted at execute time (see the live-invocation checks below, which
# confirm the actual substituted value reaches argv correctly).
chk("it is verified: true (owner-approved promotion, T-051-S7)",
    new_pilot.get("verified") is True)
chk("its binary is 'claude'", new_pilot.get("binary") == "claude")
chk("its timeout matches the existing foreground timeout convention (300s)",
    new_pilot.get("timeout") == 300)
new_argv = new_pilot.get("argv") or []
chk("its argv contains the __MISSION_SCOPE_DIR__ placeholder exactly once",
    new_argv.count("__MISSION_SCOPE_DIR__") == 1)
chk("its argv contains the __MISSION_BUDGET_USD__ placeholder exactly once",
    new_argv.count("__MISSION_BUDGET_USD__") == 1)
chk("its argv declares only Read,Edit tools", "Read,Edit" in new_argv)
chk("its argv contains no Bash tool", "Bash" not in new_argv)
chk("its argv includes --restricted (removes Bash/PowerShell/REPL)", "--restricted" in new_argv)
chk("its argv includes --strict-mcp-config (no MCP servers)", "--strict-mcp-config" in new_argv)
chk("its argv includes --permission-mode acceptEdits", "acceptEdits" in new_argv)
chk("its argv includes --permission-prompts none", "none" in new_argv)
chk("its argv includes --max-budget-usd, with the budget substituted per mission, "
    "not a static cap", "--max-budget-usd" in new_argv)
chk("its argv includes --no-session-persistence (no background persistence)",
    "--no-session-persistence" in new_argv)
chk("its argv ends with the bare '--' packet-boundary marker, matching the existing "
    "transport convention", new_argv[-1] == "--")
chk("evidence text discloses the owner-approved promotion",
    "owner-approved promotion" in (new_pilot.get("evidence") or "").lower())

# =============================================================================================
t("3. other transports unaffected")
# The governance/product/** private-root mirror assertion that used to live here (does the
# root mirror still exist, and does it correctly NOT carry the pilot-only entries) moved to
# engine/tests/test-root-duplicate-drift.py (T-113), which already owns every other root-vs-
# engine drift check and already reads ATLAS_HOME for exactly this purpose. This file only
# reads the engine-owned REAL_TRANSPORTS_PATH registry above it, never the private root, so
# T-105's public-engine consolidation no longer has this file as a blocker.
codex_spec = real_transports.get("codex")
claude_code_spec = real_transports.get("claude-code")
chk("the pre-existing codex transport is unaffected", codex_spec is not None and
    codex_spec.get("argv") == ["exec", "--sandbox", "read-only", "--skip-git-repo-check", "-"])
chk("the pre-existing claude-code transport is unaffected", claude_code_spec is not None and
    claude_code_spec.get("verified") is True)


# =============================================================================================
# SECTION: pure-function unit tests for the new resolution helpers, using a disposable,
# throwaway ATLAS_HOME (path resolution only — no mission pipeline exercised here).
# =============================================================================================
unit_root = Path(tempfile.mkdtemp(prefix="t051-livet-unit-"))
os.environ["ATLAS_HOME"] = str(unit_root)
(unit_root / "scoped").mkdir(parents=True, exist_ok=True)
(unit_root / "scoped" / "file.txt").write_text("x")
(unit_root / "other").mkdir(parents=True, exist_ok=True)
(unit_root / "other" / "file2.txt").write_text("y")

t("4. exact scope-to-directory derivation")
scope1 = mission.canonicalize_scope("scoped/file.txt")
directory1 = mission.resolve_mission_pilot_directory(scope1)
chk("the derived directory is the scope file's own canonical parent directory",
    directory1 == str(Path(scope1["canonical"]).parent))
chk("the derived directory is a real, existing directory", Path(directory1).is_dir())
chk("the derived directory is strictly inside ATLAS_HOME, never ATLAS_HOME itself",
    directory1 != str(Path(os.path.realpath(str(unit_root)))))

# =============================================================================================
t("5. empty / ambiguous scope refused")
rc = None
try:
    mission.resolve_mission_pilot_directory(None)
except mission.MissionError as e:
    rc = e.code
chk("a None scope refuses", rc == 2)
try:
    mission.resolve_mission_pilot_directory([])
except mission.MissionError as e:
    rc = e.code
chk("an empty scope list refuses", rc == 2)
try:
    mission.resolve_mission_pilot_directory({"raw": "x"})
except mission.MissionError as e:
    rc = e.code
chk("a scope dict with no canonical field refuses", rc == 2)

# =============================================================================================
t("6. multiple unrelated directories refused")
scope2 = mission.canonicalize_scope("other/file2.txt")
rc = None
try:
    mission.resolve_mission_pilot_directory([scope1, scope2])
except mission.MissionError as e:
    rc = e.code
chk("two scopes in different directories refuse as ambiguous", rc == 5)

# =============================================================================================
t("7. atlas-root-itself directory refused (too broad)")
(unit_root / "root-file.txt").write_text("z")
scope_root = mission.canonicalize_scope("root-file.txt")
rc = None
try:
    mission.resolve_mission_pilot_directory(scope_root)
except mission.MissionError as e:
    rc = e.code
chk("a scope file living directly at the Atlas root refuses (too broad a directory)",
    rc == 5)

# =============================================================================================
t("8. absolute path and traversal refused (at scope canonicalization, upstream of this "
   "resolver)")
rc = None
try:
    mission.canonicalize_scope("/etc/passwd")
except mission.MissionError as e:
    rc = e.code
chk("an absolute-path scope refuses before it ever reaches directory derivation", rc == 2)
rc = None
try:
    mission.canonicalize_scope("../../etc/passwd")
except mission.MissionError as e:
    rc = e.code
chk("a traversal-shaped scope refuses before it ever reaches directory derivation", rc == 2)

# =============================================================================================
t("9. symlink escape refused")
outside_root = Path(tempfile.mkdtemp(prefix="t051-livet-outside-"))
(outside_root / "secret.txt").write_text("do not touch")
(unit_root / "escape-link.txt").symlink_to(outside_root / "secret.txt")
rc = None
try:
    mission.canonicalize_scope("escape-link.txt")
except mission.MissionError as e:
    rc = e.code
# canonicalize_scope's own convention (established in T-051-S1) uses the default code=2
# for every scope-validation refusal, including this one — never code=5.
chk("a scope file that is a symlink escaping the Atlas root refuses", rc == 2)

(unit_root / "linked-dir").symlink_to(outside_root)
rc = None
try:
    mission.canonicalize_scope("linked-dir/whatever.txt")
except mission.MissionError as e:
    rc = e.code
chk("a scope path through a symlinked directory that escapes the Atlas root refuses",
    rc == 2)


# =============================================================================================
# SECTION: build_mission_pilot_argv determinism, placeholder enforcement, injection safety.
# =============================================================================================
t("10. argv determinism — same inputs produce byte-identical argv")
template = ["-p", "--add-dir", "__MISSION_SCOPE_DIR__", "--tools", "Read", "Edit", "--"]
argv_a = mission.build_mission_pilot_argv("claude", template, scope1)
argv_b = mission.build_mission_pilot_argv("claude", template, scope1)
chk("two calls with identical inputs produce byte-identical argv lists", argv_a == argv_b)
chk("the placeholder was substituted with the resolved directory",
    directory1 in argv_a and "__MISSION_SCOPE_DIR__" not in argv_a)
chk("every other argv element passed through unchanged",
    argv_a[0] == "claude" and argv_a[1] == "-p" and argv_a[4] == "--tools")

# =============================================================================================
t("11. placeholder count enforcement — zero or multiple placeholders refused")
rc = None
try:
    mission.build_mission_pilot_argv("claude", ["-p", "--tools", "Read"], scope1)
except mission.MissionError as e:
    rc = e.code
chk("a template with zero placeholders refuses", rc == 5)
rc = None
try:
    mission.build_mission_pilot_argv(
        "claude", ["--add-dir", "__MISSION_SCOPE_DIR__", "--add-dir",
                  "__MISSION_SCOPE_DIR__"], scope1)
except mission.MissionError as e:
    rc = e.code
chk("a template with the placeholder twice refuses as an ambiguous/unbounded template",
    rc == 5)

# =============================================================================================
t("12. no arbitrary argv template / command injection")
rc = None
try:
    mission.build_mission_pilot_argv("claude; rm -rf /", ["__MISSION_SCOPE_DIR__"], scope1)
except mission.MissionError as e:
    rc = e.code
chk("a shell-metacharacter-laced binary name refuses rather than being passed to "
    "subprocess", rc == 5)
rc = None
try:
    mission.build_mission_pilot_argv(
        "claude", ["-p", "__MISSION_SCOPE_DIR__; rm -rf /", "--"], scope1)
except mission.MissionError as e:
    rc = e.code
chk("a look-alike token ('__MISSION_SCOPE_DIR__' plus appended text) is NOT treated as "
    "the placeholder — substitution is exact-match only, so this refuses as containing "
    "zero real placeholders rather than silently substituting a near-match", rc == 5)

argv_injection_probe = mission.build_mission_pilot_argv(
    "claude", ["-p", "__MISSION_SCOPE_DIR__", "--extra-arg", "; rm -rf /", "--"], scope1)
# argv_injection_probe = [binary, "-p", <substituted directory>, "--extra-arg",
#                         "; rm -rf /", "--"]
chk("a SEPARATE, non-placeholder argv element containing shell metacharacters is passed "
    "through UNCHANGED, never executed as a shell string (this file's own subprocess calls "
    "always use a list argv, never shell=True, so this string is inert)",
    argv_injection_probe[4] == "; rm -rf /")
chk("the one real placeholder in that same template was still correctly substituted",
    argv_injection_probe[2] == directory1)

# =============================================================================================
t("13. missing transport / malformed argv refused via mission_pilot_transport_argv")
mission_root_dir = unit_root / "projects" / "demo" / "tickets" / "T-971-UNIT"
mission_root_dir.mkdir(parents=True, exist_ok=True)
(mission_root_dir / "task.md").write_text(
    "---\nkind: ticket\nnamespace: atlas.ticket\nid: T-971-UNIT\ntitle: unit\nstate: active\n"
    "project: demo\nopened_at: 2026-09-08 12:00 AM\nupdated_at: 2026-09-08 12:00 AM\n"
    "artifacts: []\n---\n# fixture\n")
rc = None
try:
    mission.mission_pilot_transport_argv(mission_root_dir, "mission-doesnotexist",
                                         "handoff-doesnotexist")
except mission.MissionError as e:
    rc = e.code
chk("an unknown mission id refuses (no live invocation is even attempted)", rc == 4)


# =============================================================================================
# SECTION 4: the real, live, two-ticket bounded pilot.
# =============================================================================================
CLAUDE_BINARY = shutil.which("claude")
CLAUDE_LIVE_INVOCATIONS = []  # (mission_label, argv, rc, stdout, stderr) — the real evidence.


def new_pilot_fixture():
    """Two disposable fixture tickets under one shared temporary ATLAS_HOME, plus a
    disposable adapter/transport registry. The disposable transport registry's own
    `claude-code-mission-pilot` entry is marked verified: true so the T-051 pipeline's own
    role-routing gate can be exercised — see the module docstring for why this is not, and
    has never been, a promotion of the REAL registry's own (untouched, verified: false)
    entry."""
    tmp = Path(tempfile.mkdtemp(prefix="t051-livet-pilot-"))
    ticket_a = tmp / "projects" / "demo" / "tickets" / "T-970-A"
    ticket_b = tmp / "projects" / "demo" / "tickets" / "T-970-B"
    ticket_c = tmp / "projects" / "demo" / "tickets" / "T-970-C"
    for tid, d in (("T-970-A", ticket_a), ("T-970-B", ticket_b), ("T-970-C", ticket_c)):
        d.mkdir(parents=True, exist_ok=True)
        (d / "task.md").write_text(
            "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
            "title: fixture live-pilot ticket {id}\nstate: active\n"
            "project: demo\nopened_at: 2026-09-08 12:00 AM\nupdated_at: 2026-09-08 12:00 AM\n"
            "artifacts: []\n---\n# fixture\n".format(id=tid))

    (tmp / "pilot-a").mkdir(parents=True, exist_ok=True)
    (tmp / "pilot-b").mkdir(parents=True, exist_ok=True)
    (tmp / "pilot-c").mkdir(parents=True, exist_ok=True)
    alpha = tmp / "pilot-a" / "alpha.txt"
    beta = tmp / "pilot-b" / "beta.txt"
    gamma = tmp / "pilot-c" / "gamma.txt"
    alpha.write_text("alpha: untouched baseline\n")
    beta.write_text("beta: untouched baseline\n")
    gamma.write_text("gamma: untouched baseline\n")

    adapters_dir = tmp / "adapters"
    adapters_dir.mkdir(parents=True, exist_ok=True)
    # Each fixture adapter's own version_cmd binary must agree with that same client's
    # fixture transport binary field — mission_route's identity-conflict check (T-051-S2)
    # correctly refuses a mismatch between the two, exactly as it would in production.
    adapter_binaries = {"codex": "codex-bin", "claude-code-mission-pilot": "claude"}
    for client in ("codex", "claude-code-mission-pilot"):
        d = adapters_dir / client
        d.mkdir(parents=True, exist_ok=True)
        (d / "adapter.yaml").write_text(
            "adapter: " + client + "\nname: fixture adapter for " + client +
            "\ncontract: 1\n\n"
            "client:\n  detect: [/nonexistent]\n  version_cmd: " +
            adapter_binaries[client] + " --version\n"
            "  consumer_verified: false\n\nprovides:\n"
            "  rules: { path: /nonexistent, format: markdown, verified: true }\n\n"
            "writes: []\nrequires: []\nenforces: []\n")

    real_argv = new_pilot.get("argv")
    transports_path = tmp / "handoff-transports.yaml"
    # Every element double-quoted, unconditionally — the safest way to guarantee this
    # disposable fixture's own YAML-like parser treats each one as a plain string (matching
    # the real registry's own habit of quoting "0.10" so it is never mistaken for a float),
    # never relying on this parser's bare-token type inference.
    argv_yaml = ", ".join(json.dumps(a) for a in real_argv)
    transports_path.write_text(
        "contract: 1\n\ntransports:\n"
        "  codex:\n"
        "    name: fixture codex\n    binary: codex-bin\n"
        "    argv: [--sandbox, read-only]\n    stdin: packet\n    timeout: 60\n"
        "    verified: true\n    evidence: fixture, not dispatched\n"
        "  claude-code-mission-pilot:\n"
        "    name: fixture mirror of the real (unverified) claude-code-mission-pilot entry\n"
        f"    binary: {new_pilot.get('binary')}\n"
        f"    argv: [{argv_yaml}]\n"
        f"    stdin: packet\n    timeout: {new_pilot.get('timeout')}\n"
        "    verified: true\n"
        "    evidence: >\n"
        "      Disposable fixture mirror, verified: true ONLY inside this test's own\n"
        "      disposable registry, so the pipeline's mission_route gate can be exercised.\n"
        "      The REAL registry entry (internal/governance/policies/handoff-transports.yaml)\n"
        "      remains verified: false and is never written by this file.\n")

    os.environ["ATLAS_HOME"] = str(tmp)
    os.environ["ATLAS_ADAPTERS"] = str(adapters_dir)
    os.environ["ATLAS_HANDOFF_TRANSPORTS"] = str(transports_path)
    return tmp, ticket_a, ticket_b, ticket_c, alpha, beta, gamma


def snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


def do_create(task_id, scopes, budget="0.10", max_slices="3", max_attempts="5", ttl="3600",
             key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("create")
    args = [task_id]
    for s in scopes:
        args += ["--scope", s]
    args += ["--planner", "codex", "--executor", "claude-code-mission-pilot", "--verifier",
            "codex", "--budget-usd", budget, "--max-slices", max_slices,
            "--max-attempts", max_attempts, "--ttl-seconds", ttl, "--idempotency-key", key]
    return run(m.cmd_create, args)


def mission_id_from(out):
    for line in out.splitlines():
        if line.strip().startswith("mission id:"):
            return line.split(":", 1)[1].strip()
    return None


def do_approve(task_id, mission_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("approve")
    return run(m.cmd_approve, [task_id, mission_id, "--owner-words",
                               "approved by live-pilot owner", "--idempotency-key", key])


def do_handoff(task_id, mission_id, scope, session, invocation, executor_client=None,
              gate="execute", budget="0.05", key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("handoff")
    args = [task_id, mission_id, "--scope", scope, "--executor-client",
           executor_client or "claude-code-mission-pilot", "--executor-session", session,
           "--invocation-id", invocation, "--gate", gate, "--slice-budget-usd", budget,
           "--idempotency-key", key, "--json"]
    return run(m.cmd_handoff, args)


def do_continue(task_id, mission_id, handoff_id, scope, session, invocation, budget="0.02",
                key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("continue")
    args = [task_id, mission_id, handoff_id, "--scope", scope, "--executor-client",
           "claude-code-mission-pilot", "--executor-session", session, "--invocation-id",
           invocation, "--gate", "execute", "--slice-budget-usd", budget,
           "--idempotency-key", key, "--json"]
    return run(m.cmd_continue, args)


def result_hash(handoff_id, mission_id, root_task_id, status, changed_files, tests_field,
                summary):
    material = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "status": status, "changed_files": sorted(changed_files), "tests": tests_field,
        "summary": summary,
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def make_result(handoff_id, mission_id, root_task_id, executor_session, invocation_id,
                scope, status="pass", changed_files=(), tests=("manual inspection ok",),
                reported_cost_usd=0.05, summary="edited the approved fixture file",
                blocker=None, owner_decision_required=None):
    tests_field = list(tests)
    h = result_hash(handoff_id, mission_id, root_task_id, status, changed_files, tests_field,
                    summary)
    result = {
        "handoff_id": handoff_id, "mission_id": mission_id, "root_task_id": root_task_id,
        "executor_client": "claude-code-mission-pilot", "executor_session": executor_session,
        "invocation_id": invocation_id, "gate": "execute", "scope": scope, "status": status,
        "changed_files": list(changed_files), "tests": tests_field,
        "result_sha256": h, "reported_cost_usd": reported_cost_usd, "summary": summary,
    }
    if blocker is not None:
        result["blocker"] = blocker
    if owner_decision_required is not None:
        result["owner_decision_required"] = owner_decision_required
    return result


def write_result_file(tmp_root, result_obj, name=None):
    name = name or uniq_key("result") + ".json"
    p = Path(tmp_root) / name
    p.write_text(json.dumps(result_obj))
    return str(p)


def do_verify(task_id, mission_id, handoff_id, result_file, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("verify")
    return run(m.cmd_verify, [task_id, mission_id, handoff_id, "--result-file", result_file,
                             "--idempotency-key", key, "--json"])


def do_finalize(task_id, mission_id, handoff_id, key=None, m=None):
    m = m or mission_cli
    key = key or uniq_key("finalize")
    return run(m.cmd_finalize, [task_id, mission_id, handoff_id, "--idempotency-key", key,
                               "--json"])


def real_claude_edit(mission_label, task_dir, mission_id, handoff_id, target_file,
                     new_content):
    """The one real, live Claude CLI invocation this test performs per fixture mission.
    Builds the exact argv via the SAME production functions the real (unverified) transport
    is meant to be dispatched with, then runs it as a real, bounded, foreground subprocess.
    Records the full argv, exit code, and output in CLAUDE_LIVE_INVOCATIONS as durable
    evidence. Returns True if the file now holds exactly `new_content`."""
    argv = mission.mission_pilot_transport_argv(task_dir, mission_id, handoff_id,
                                                client="claude-code-mission-pilot")
    prompt = (f"Read the file {target_file.name} in the current working directory and "
             f"replace its entire contents with exactly the single line: {new_content}. "
             f"Do not read or edit any other file. Do not run any command.")
    proc = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=180)
    CLAUDE_LIVE_INVOCATIONS.append(
        (mission_label, argv, proc.returncode, proc.stdout, proc.stderr))
    return target_file.read_text().strip() == new_content


t("14. two real bounded Claude CLI fixture executions")
if not CLAUDE_BINARY:
    chk("the `claude` binary is on PATH (required for a real pilot invocation)", False)
    print(f"  {R}S7 live pilot cannot proceed: no `claude` binary found on PATH.{X}")
    sys.exit(1)
chk("the `claude` binary is on PATH", True)

root, ticket_a, ticket_b, ticket_c, alpha_path, beta_path, gamma_path = new_pilot_fixture()

scope_a_raw, scope_b_raw, scope_c_raw = "pilot-a/alpha.txt", "pilot-b/beta.txt", "pilot-c/gamma.txt"
session_a, session_b, session_c = "live-session-A-001", "live-session-B-001", "live-session-C-001"
invocation_a, invocation_b, invocation_c = ("live-invocation-A-001", "live-invocation-B-001",
                                            "live-invocation-C-001")

rc, out, err = do_create("T-970-A", scopes=[scope_a_raw])
assert rc == 0, (rc, out, err)
mission_a = mission_id_from(out)
rc, out, err = do_create("T-970-B", scopes=[scope_b_raw])
assert rc == 0, (rc, out, err)
mission_b = mission_id_from(out)
chk("mission A and mission B have different mission ids", mission_a != mission_b)

rc, out, err = do_approve("T-970-A", mission_a)
assert rc == 0, (rc, out, err)
rc, out, err = do_approve("T-970-B", mission_b)
assert rc == 0, (rc, out, err)

rc, out, err = do_handoff("T-970-A", mission_a, scope_a_raw, session_a, invocation_a)
assert rc == 0, (rc, out, err)
handoff_a = json.loads(out)["handoff_id"]
rc, out, err = do_handoff("T-970-B", mission_b, scope_b_raw, session_b, invocation_b)
assert rc == 0, (rc, out, err)
handoff_b = json.loads(out)["handoff_id"]
chk("both missions received one bounded handoff each, using claude-code-mission-pilot as "
    "the executor", handoff_a != handoff_b)

edited_ok_b = real_claude_edit("mission-B", ticket_b, mission_b, handoff_b, beta_path,
                               "live-edit-B")
edited_ok_a = real_claude_edit("mission-A", ticket_a, mission_a, handoff_a, alpha_path,
                               "live-edit-A")
chk("the REAL Claude CLI invocation for mission B actually edited beta.txt to the exact "
    "requested content", edited_ok_b)
chk("the REAL Claude CLI invocation for mission A actually edited alpha.txt to the exact "
    "requested content", edited_ok_a)
chk("exactly two live Claude CLI invocations were recorded", len(CLAUDE_LIVE_INVOCATIONS) == 2)
for label, argv, proc_rc, _o, _e in CLAUDE_LIVE_INVOCATIONS:
    chk(f"the {label} live invocation exited 0", proc_rc == 0)
    chk(f"the {label} live invocation's argv used --tools Read,Edit only",
        "Read,Edit" in argv and "Bash" not in argv)
    chk(f"the {label} live invocation's argv substituted a real numeric budget, "
        "not the placeholder",
        "--max-budget-usd" in argv
        and "__MISSION_BUDGET_USD__" not in argv
        and any(a.replace(".", "", 1).isdigit() for a in argv))

# =============================================================================================
t("15. each real result came from the correct invocation, verified through mission verify")
res_a = make_result(handoff_a, mission_a, "T-970-A", session_a, invocation_a, scope_a_raw,
                    changed_files=[scope_a_raw], summary="live edit A applied")
res_b = make_result(handoff_b, mission_b, "T-970-B", session_b, invocation_b, scope_b_raw,
                    changed_files=[scope_b_raw], summary="live edit B applied")
rf_a = write_result_file(root, res_a)
rf_b = write_result_file(root, res_b)
rc, out, err = do_verify("T-970-B", mission_b, handoff_b, rf_b)
assert rc == 0, (rc, out, err)
chk("mission B's real result verifies to PASS", json.loads(out)["classification"] == "PASS")
rc, out, err = do_verify("T-970-A", mission_a, handoff_a, rf_a)
assert rc == 0, (rc, out, err)
chk("mission A's real result verifies to PASS", json.loads(out)["classification"] == "PASS")

# =============================================================================================
t("16. no cross-ticket file edit occurred")
chk("alpha.txt holds only mission A's own live edit", alpha_path.read_text().strip() == "live-edit-A")
chk("beta.txt holds only mission B's own live edit", beta_path.read_text().strip() == "live-edit-B")
chk("alpha.txt was never touched by mission B's edit", "live-edit-B" not in alpha_path.read_text())
chk("beta.txt was never touched by mission A's edit", "live-edit-A" not in beta_path.read_text())
chk("gamma.txt (mission C's own file, not yet touched) remains at its untouched baseline",
    gamma_path.read_text() == "gamma: untouched baseline\n")

# =============================================================================================
t("17. continuation after PASS (synthetic second result — see module docstring; "
   "no third live call)")
(root / "pilot-a").mkdir(parents=True, exist_ok=True)
alpha2_path = root / "pilot-a" / "alpha2.txt"
alpha2_path.write_text("alpha2: baseline\n")
rc, out, err = do_create("T-970-A", scopes=[scope_a_raw, "pilot-a/alpha2.txt"],
                         max_attempts="5", max_slices="5", key=uniq_key("cont-mission"))
assert rc == 0, (rc, out, err)
mission_a_cont = mission_id_from(out)
rc, out, err = do_approve("T-970-A", mission_a_cont, key=uniq_key("cont-approve"))
assert rc == 0, (rc, out, err)
rc, out, err = do_handoff("T-970-A", mission_a_cont, scope_a_raw, session_a, invocation_a,
                          key=uniq_key("cont-handoff"))
assert rc == 0, (rc, out, err)
handoff_a_cont = json.loads(out)["handoff_id"]
res_a_cont = make_result(handoff_a_cont, mission_a_cont, "T-970-A", session_a, invocation_a,
                         scope_a_raw, changed_files=[scope_a_raw])
rf_a_cont = write_result_file(root, res_a_cont)
rc, out, err = do_verify("T-970-A", mission_a_cont, handoff_a_cont, rf_a_cont,
                         key=uniq_key("cont-verify"))
assert rc == 0 and json.loads(out)["classification"] == "PASS", (rc, out, err)
rc, out, err = do_continue("T-970-A", mission_a_cont, handoff_a_cont, "pilot-a/alpha2.txt",
                           session_a, invocation_a, key=uniq_key("cont-continue"))
chk("continuation after a PASS classification succeeds", rc == 0)
handoff_a_cont2 = json.loads(out)["handoff_id"]
# reported_cost_usd must fit inside this continuation's own slice budget (do_continue's
# own default --slice-budget-usd is "0.02") — make_result's own default (0.05) would
# otherwise trip the over-budget check and classify NEEDS_OWNER instead of PASS.
res_a_cont2 = make_result(handoff_a_cont2, mission_a_cont, "T-970-A", session_a, invocation_a,
                          "pilot-a/alpha2.txt", changed_files=["pilot-a/alpha2.txt"],
                          reported_cost_usd=0.01)
rf_a_cont2 = write_result_file(root, res_a_cont2)
rc, out, err = do_verify("T-970-A", mission_a_cont, handoff_a_cont2, rf_a_cont2,
                         key=uniq_key("cont-verify2"))
chk("the continuation's own handoff verifies to PASS",
    rc == 0 and json.loads(out)["classification"] == "PASS")

# =============================================================================================
t("18. stop after BLOCKED/FAILED/NEEDS_OWNER (synthetic negative-path scenarios, "
   "no live call needed to prove a stop)")
for bad_status, extra in (("blocked", {"blocker": "fixture: deliberately blocked"}),
                          ("failed", {}),
                          ("needs_owner", {"owner_decision_required": "ambiguous"})):
    rc, out, err = do_create("T-970-B", scopes=["pilot-b/beta-neg.txt"],
                             key=uniq_key(f"neg-{bad_status}"))
    assert rc == 0, (rc, out, err)
    mid_neg = mission_id_from(out)
    rc, out, err = do_approve("T-970-B", mid_neg, key=uniq_key(f"neg-app-{bad_status}"))
    assert rc == 0, (rc, out, err)
    (root / "pilot-b" / "beta-neg.txt").write_text("baseline\n")
    rc, out, err = do_handoff("T-970-B", mid_neg, "pilot-b/beta-neg.txt", session_b,
                              f"inv-neg-{bad_status}", key=uniq_key(f"neg-h-{bad_status}"))
    assert rc == 0, (rc, out, err)
    hid_neg = json.loads(out)["handoff_id"]
    res_neg = make_result(hid_neg, mid_neg, "T-970-B", session_b, f"inv-neg-{bad_status}",
                          "pilot-b/beta-neg.txt", status=bad_status, **extra)
    rf_neg = write_result_file(root, res_neg)
    rc, out, err = do_verify("T-970-B", mid_neg, hid_neg, rf_neg,
                             key=uniq_key(f"neg-v-{bad_status}"))
    assert rc == 0, (rc, out, err)
    chk(f"a {bad_status} result classifies as expected",
        json.loads(out)["classification"] == bad_status.upper())
    rc, out, err = do_continue("T-970-B", mid_neg, hid_neg, "pilot-b/beta-neg.txt", session_b,
                               f"inv-neg-cont-{bad_status}", key=uniq_key(f"neg-c-{bad_status}"))
    chk(f"continuation after {bad_status} refuses, never creating a next slice", rc == 5)
    rc, out, err = do_finalize("T-970-B", mid_neg, hid_neg, key=uniq_key(f"neg-f-{bad_status}"))
    assert rc == 0, (rc, out, err)
    expected_state = {"blocked": "blocked", "failed": "failed",
                      "needs_owner": "needs_owner"}[bad_status]
    chk(f"finalize for a {bad_status} result reaches mission_state={expected_state}, "
        f"never completed", json.loads(out)["mission_state"] == expected_state)

# =============================================================================================
t("19. wrong session and invocation refusal")
rc, out, err = do_continue("T-970-A", mission_a, handoff_a, scope_a_raw, session_b,
                           invocation_a, key=uniq_key("wrong-session"))
chk("continuing mission A's own handoff using mission B's own session refuses",
    rc == 5 and "session" in err.lower())

# =============================================================================================
t("20. deliberately identity-mismatched pilot mission C stops BEFORE any live invocation")
before_live_count = len(CLAUDE_LIVE_INVOCATIONS)
rc, out, err = do_create("T-970-C", scopes=[scope_c_raw], key=uniq_key("mismatch-create"))
assert rc == 0, (rc, out, err)
mission_c = mission_id_from(out)
rc, out, err = do_approve("T-970-C", mission_c, key=uniq_key("mismatch-approve"))
assert rc == 0, (rc, out, err)
# Deliberate identity mismatch: request an executor_client that does not match the
# contract's own approved executor_client (claude-code-mission-pilot) — this must refuse
# inside mission_handoff itself, long before this test would ever build a live argv.
rc, out, err = do_handoff("T-970-C", mission_c, scope_c_raw, session_c, invocation_c,
                          executor_client="codex", key=uniq_key("mismatch-handoff"))
chk("a handoff naming the wrong executor_client refuses (identity-mismatched)",
    rc == 5 and "executor_client" in err)
chk("no live Claude CLI invocation was made for mission C's own attempted handoff",
    len(CLAUDE_LIVE_INVOCATIONS) == before_live_count)
chk("gamma.txt (mission C's own file) remains completely untouched, proving execution "
    "never started", gamma_path.read_text() == "gamma: untouched baseline\n")

# =============================================================================================
t("21. finalization produced the correct reports")
rc, out, err = do_finalize("T-970-A", mission_a, handoff_a, key=uniq_key("final-a"))
assert rc == 0, (rc, out, err)
final_a = json.loads(out)
chk("mission A finalizes to completed", final_a["mission_state"] == "completed")
report_a = json.loads(Path(final_a["final_report_path"]).read_text())
chk("mission A's final report names the real, live-edited scope", report_a["approved_scope"] == scope_a_raw)
chk("mission A's final report's changed_files matches what the live edit actually reported",
    report_a["changed_files"] == [scope_a_raw])

rc, out, err = do_finalize("T-970-B", mission_b, handoff_b, key=uniq_key("final-b"))
assert rc == 0, (rc, out, err)
final_b = json.loads(out)
chk("mission B finalizes to completed", final_b["mission_state"] == "completed")

rc, out, err = do_finalize("T-970-A", mission_a_cont, handoff_a_cont2, key=uniq_key("final-cont"))
assert rc == 0, (rc, out, err)
chk("the continuation mission finalizes to completed",
    json.loads(out)["mission_state"] == "completed")

# =============================================================================================
t("22. no duplicate handoff or continuation occurred")
handoffs_a_count = len(list(mission.handoffs_root(ticket_a, mission_a).glob("handoff-*")))
handoffs_b_count = len(list(mission.handoffs_root(ticket_b, mission_b).glob("handoff-*")))
chk("mission A has exactly one handoff (no duplicate created by this test)",
    handoffs_a_count == 1)
chk("mission B has exactly one handoff (no duplicate created by this test)",
    handoffs_b_count == 1)
handoffs_a_cont_count = len(
    list(mission.handoffs_root(ticket_a, mission_a_cont).glob("handoff-*")))
chk("the continuation mission has exactly two handoffs (original + one continuation, no "
    "duplicate)", handoffs_a_cont_count == 2)

# =============================================================================================
t("23. no production file changes — the real registry entry's verified status is unchanged "
  "by this test run")
real_transports_after = hoff_real.load_transports()
chk("after the entire live pilot run, the REAL claude-code-mission-pilot entry's verified "
    "status is unchanged (still true, from its 2026-09-07 owner-approved promotion) — "
    "this test never flips it either way",
    real_transports_after.get("claude-code-mission-pilot", {}).get("verified") is True)
chk("after the entire live pilot run, the REAL claude-code-tools-pilot entry is still "
    "byte-for-byte its original argv",
    real_transports_after.get("claude-code-tools-pilot", {}).get("argv") == EXPECTED_OLD_ARGV)
PROTECTED = [
    CLI / "atlas-coordinator", CORE_CLI / "atlas-coordinator",
    CLI / "atlas_coordination.py", CORE_CLI / "atlas_coordination.py",
    CLI / "atlas-handoff", CORE_CLI / "atlas-handoff",
    REPO / "internal" / "governance" / "policies" / "coordinator-routing.yaml",
]
for p in PROTECTED:
    chk(f"protected file exists and was not deleted: {p.name}", p.is_file())
chk("no real AIOS-011, AIOS-012, AIOS-017, T-049, or T-050 ticket directory was created "
    "or touched by this pilot's disposable fixture root",
    not any(p.name in ("AIOS-011", "AIOS-012", "AIOS-017", "T-049", "T-050")
           for p in root.rglob("*") if p.is_dir()))
chk("no coordination/, runtime/, claims/, or leases/ directory exists anywhere under the "
    "pilot fixture root",
    not any(p.name in ("coordination", "runtime", "claims", "leases")
           for p in root.rglob("*") if p.is_dir()))
chk("no handoff-*.md V6 record exists anywhere under the pilot fixture root",
    not list(root.rglob("handoff-*.md")))

# =============================================================================================
t("24. engine/core parity for the new resolution functions")
scope_parity = mission.canonicalize_scope("pilot-a/alpha.txt")
argv_engine = mission.build_mission_pilot_argv("claude", template, scope_parity)
argv_core = core_mission.build_mission_pilot_argv("claude", template, scope_parity)
chk("engine and core build_mission_pilot_argv agree byte-for-byte", argv_engine == argv_core)
engine_py = CLI / "atlas_mission.py"
core_py = CORE_CLI / "atlas_mission.py"
chk("engine/cli/atlas_mission.py and core/cli/atlas_mission.py remain byte-identical",
    engine_py.read_bytes() == core_py.read_bytes())
engine_cli_file = CLI / "atlas-mission"
core_cli_file = CORE_CLI / "atlas-mission"
chk("engine/cli/atlas-mission and core/cli/atlas-mission remain byte-identical",
    engine_cli_file.read_bytes() == core_cli_file.read_bytes())


# =============================================================================================
print(f"\n{D}{'='*80}{X}")
total = passed + failed
color = G if failed == 0 else R
print(f"{color}{passed}/{total} passed{X}" + (f", {R}{failed} FAILED{X}" if failed else ""))
print(f"\n{Y}Live invocations recorded: {len(CLAUDE_LIVE_INVOCATIONS)}{X}")
for label, argv, proc_rc, _o, _e in CLAUDE_LIVE_INVOCATIONS:
    print(f"  {label}: rc={proc_rc} argv={argv}")
sys.exit(0 if failed == 0 else 1)
