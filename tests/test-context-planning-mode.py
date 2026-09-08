#!/usr/bin/env python3
"""tests/test-context-planning-mode.py — T-034: `atlas context --mode planning`.

`atlas-context`'s canonical, dispatched copy lives at ~/atlas/context/atlas-context (cut
over by T-016); the repo's cli/atlas-context is historical only and is not exercised here.
This file tests that live file directly, against a disposable ATLAS_HOME, so nothing here
touches the real workspace.

Scope: `--mode planning` is a pure reorganization of the packet `build()` already computes
— same project/git/ticket evidence, no new reads, no ranking. It must:
  - print project, git state, per-ticket id/state/title/next-action(first line)/blockers,
    and read-next pointers
  - omit objective/verification prose, the recent log and artifacts
  - leave `atlas context` (no flags) and `atlas context --json` (alone) unchanged
  - reject `--mode planning --boundary` and `--mode planning --json`, both exit 2
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_CONTEXT = Path.home() / "atlas" / "context" / "atlas-context"

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


if not LIVE_CONTEXT.is_file():
    print("  (skipped — no ~/atlas/context/atlas-context found on this machine; nothing "
          "to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)


def make_ticket(home, project, ticket_id, state="active", next_action="do the thing",
                 objective="a long objective paragraph that must never leak into "
                           "planning output",
                 verification="a long verification paragraph that must never leak "
                              "into planning output either",
                 blockers=None, log_line="- 2026-09-05: something happened",
                 artifacts=None):
    d = home / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    body = (f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
            f"project: {project}\nopened: 2026-09-05\nupdated: 2026-09-05\n---\n\n"
            f"## Objective\n\n{objective}\n\n"
            f"## Next action\n\n{next_action}\n\n"
            f"## Verification\n\n{verification}\n\n")
    if blockers:
        body += f"## Blockers\n\n{blockers}\n\n"
    body += f"## Log\n\n{log_line}\n"
    (d / "task.md").write_text(body)
    if artifacts:
        for name in artifacts:
            (d / name).write_text("placeholder")
    return d


def registry(home, project, path):
    reg = home / "projects" / "registry.md"
    reg.parent.mkdir(parents=True, exist_ok=True)
    existing = reg.read_text() if reg.exists() else "| Project | Path |\n|---|---|\n"
    reg.write_text(existing + f"| {project} | {path} |\n")


def run(home, *args, cwd=None):
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run([sys.executable, str(LIVE_CONTEXT), *args],
                          cwd=cwd or str(home), env=env, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    project_dir = make_ticket(home, "fixtureproj", "T-900", state="active",
                              next_action="first line of next action\nsecond line "
                                          "that must not appear",
                              blockers="waiting on a real blocker").parent.parent
    make_ticket(home, "fixtureproj", "T-901", state="blocked",
                next_action="unblock the other thing",
                artifacts=["design.md"])
    registry(home, "fixtureproj", str(project_dir))

    t("--mode planning: required fields present")
    r = run(home, "--mode", "planning", cwd=str(project_dir))
    chk("exits 0", r.returncode == 0)
    chk("shows both ticket ids", "T-900" in r.stdout and "T-901" in r.stdout)
    chk("shows ticket state", "active" in r.stdout and "blocked" in r.stdout)
    chk("shows ticket title", "fixture T-900" in r.stdout)
    chk("next action truncated to first line",
        "first line of next action" in r.stdout
        and "second line that must not appear" not in r.stdout)
    chk("blocker shown when present", "waiting on a real blocker" in r.stdout)
    chk("read-next pointers present", "read next" in r.stdout and "atlas tickets list" in r.stdout)

    t("--mode planning: omits prose/log/artifacts")
    chk("no objective prose", "must never leak into planning output" not in r.stdout
        or "long objective paragraph" not in r.stdout)
    chk("no verification prose", "long verification paragraph" not in r.stdout)
    chk("no recent log entry", "something happened" not in r.stdout)
    chk("no artifacts/beside-it line", "beside it" not in r.stdout and "design.md" not in r.stdout)

    t("--mode planning: no ranking — same order as default render")
    default = run(home, cwd=str(project_dir))
    def ticket_order(text):
        return [line.split()[1] for line in text.splitlines()
                if line.strip().startswith(("T-900", "T-901"))
                or (len(line.split()) > 1 and line.split()[1] in ("T-900", "T-901"))]
    chk("planning output lists tickets in the same order as the default render",
        ticket_order(r.stdout) == ticket_order(default.stdout))

    t("--mode planning --boundary is rejected")
    r2 = run(home, "--mode", "planning", "--boundary", cwd=str(project_dir))
    chk("exits 2", r2.returncode == 2)
    chk("clear error naming both flags",
        "--boundary" in r2.stderr and "--mode" in r2.stderr)

    t("--mode planning --json is rejected (no silent full-JSON fallback)")
    r3 = run(home, "--mode", "planning", "--json", cwd=str(project_dir))
    chk("exits 2", r3.returncode == 2)
    chk("clear error naming both flags", "--json" in r3.stderr and "--mode" in r3.stderr)

    t("--mode with an unrecognized value is rejected")
    r4 = run(home, "--mode", "bogus", cwd=str(project_dir))
    chk("exits 2", r4.returncode == 2)

    t("default `atlas context` output is unaffected")
    focused_default = run(home, "T-900", cwd=str(project_dir))
    chk("exits 0", focused_default.returncode == 0)
    chk("focused default render still includes objective prose",
        "long objective paragraph" in focused_default.stdout)
    chk("focused default render still includes verification prose",
        "long verification paragraph" in focused_default.stdout)
    chk("focused default render still includes the recent log",
        "something happened" in focused_default.stdout)

    t("`--json` alone is unaffected")
    rj = run(home, "--json", cwd=str(project_dir))
    chk("exits 0", rj.returncode == 0)
    chk("still prints the full JSON packet", rj.stdout.strip().startswith("{"))
    chk("full packet includes tickets_live", '"tickets_live"' in rj.stdout)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
