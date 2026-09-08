#!/usr/bin/env python3
"""tests/test-context-next-mode.py — T-041: `atlas context --mode next`.

`atlas-context`'s canonical, dispatched copy lives at ~/atlas/context/atlas-context (cut
over by T-016, same file T-034's `--mode planning` test exercises). This file tests that
live file directly, against a disposable ATLAS_HOME/ATLAS_HOME, so nothing here touches
the real workspace.

Scope: `--mode next` must produce the exact same recommendation `atlas tickets next`
would for the same records (both call `atlas_tickets.classify_and_rank`/
`render_recommendation` — one implementation, two callers) and must:
  - compose with --json, unlike --mode planning
  - accept --goal/--limit/--why only together with --mode next
  - leave `atlas context` (no flags) and `atlas context --mode planning` unchanged
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_CONTEXT = Path.home() / "atlas" / "context" / "atlas-context"
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


if not LIVE_CONTEXT.is_file():
    print("  (skipped — no ~/atlas/context/atlas-context found on this machine; nothing "
          "to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)


def make_ticket(home, project, ticket_id, state="active", extra_frontmatter="",
                 next_action="do the thing"):
    d = home / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
        f"project: {project}\n\nopened_at: 2026-09-06 1:00 PM\nupdated_at: 2026-09-06 1:00 PM\n\n"
        f"artifacts: []\n{extra_frontmatter}\nchecklist:\n  - \"[x] one\"\n\n"
        f"checkpoint:\n  current: in progress\n  updated_at: 2026-09-06 1:00 PM\n---\n\n"
        f"## Next action\n\n{next_action}\n"
    )
    return d


def registry(home, project, path):
    reg = home / "projects" / "registry.md"
    reg.parent.mkdir(parents=True, exist_ok=True)
    existing = reg.read_text() if reg.exists() else "| Project | Path |\n|---|---|\n"
    reg.write_text(existing + f"| {project} | {path} |\n")


def run_context(home, *args, cwd=None):
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run([sys.executable, str(LIVE_CONTEXT), *args],
                          cwd=cwd or str(home), env=env, capture_output=True, text=True)


def run_tickets(home, *args, cwd=None):
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run([str(CLI / "atlas-tickets"), *args],
                          cwd=cwd or str(home), env=env, capture_output=True, text=True)


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    project_dir = make_ticket(home, "fixtureproj", "T-900", extra_frontmatter=(
        "priority: level_1\nrelation: parent\ngoal: ship the fixture\n")).parent.parent
    make_ticket(home, "fixtureproj", "T-901", extra_frontmatter=(
        "priority: level_2\nparent: T-900\nrelation: required\ngoal: ship the fixture\n"
        "unblocks: [T-900]\n"))
    make_ticket(home, "fixtureproj", "T-902", state="blocked",
                extra_frontmatter="priority: level_3\nblocked_by: dependency\n")
    registry(home, "fixtureproj", str(project_dir))

    t("--mode next: buckets both tickets, composes with --json")
    r = run_context(home, "--mode", "next", "--json", cwd=str(project_dir))
    chk("exits 0", r.returncode == 0)
    data = json.loads(r.stdout)
    chk("all five buckets present", set(data.keys()) ==
        {"do_now", "owner_decisions", "blocked", "paused", "quick_wins", "future"})
    chk("both live tickets accounted for across buckets",
        {"T-900", "T-901"} <= {e["id"] for e in data["do_now"]})
    chk("the blocked ticket lands in blocked, not do_now",
        "T-902" in [e["id"] for e in data["blocked"]]
        and "T-902" not in [e["id"] for e in data["do_now"]])

    t("--mode next --why: text output carries the explanation line")
    r = run_context(home, "--mode", "next", "--goal", "ship the fixture", "--why",
                    cwd=str(project_dir))
    chk("exits 0", r.returncode == 0)
    chk("required-by-parent reason present", "required by parent T-900" in r.stdout)
    chk("goal-match reason present", "matches the requested goal" in r.stdout)
    chk("unblocks reason present", "unblocks T-900" in r.stdout)

    t("--mode next agrees with `atlas tickets next` for the same records")
    ctx = run_context(home, "--mode", "next", "--json", cwd=str(project_dir))
    tix = run_tickets(home, "next", "--project", "fixtureproj", "--json")
    ctx_ids = sorted(e["id"] for bucket in json.loads(ctx.stdout).values() for e in bucket)
    tix_ids = sorted(e["id"] for bucket in json.loads(tix.stdout).values() for e in bucket)
    chk("both commands see the same three tickets", ctx_ids == tix_ids == ["T-900", "T-901", "T-902"])
    ctx_do_now = {e["id"] for e in json.loads(ctx.stdout)["do_now"]}
    tix_do_now = {e["id"] for e in json.loads(tix.stdout)["do_now"]}
    chk("both commands agree on Do now membership", ctx_do_now == tix_do_now)

    t("--mode next --limit caps results")
    r = run_context(home, "--mode", "next", "--limit", "1", "--json", cwd=str(project_dir))
    data = json.loads(r.stdout)
    chk("do_now capped at 1", len(data["do_now"]) <= 1)

    t("--goal/--limit/--why require --mode next")
    r = run_context(home, "--goal", "x", cwd=str(project_dir))
    chk("rejected with exit 2", r.returncode == 2 and "require --mode next" in r.stderr)

    t("--mode planning is unaffected by this change")
    r = run_context(home, "--mode", "planning", cwd=str(project_dir))
    chk("still exits 0", r.returncode == 0)
    chk("still shows tickets, unranked", "T-900" in r.stdout and "T-901" in r.stdout)
    r = run_context(home, "--mode", "planning", "--json", cwd=str(project_dir))
    chk("--mode planning --json is still rejected, exit 2", r.returncode == 2)

    t("default `atlas context` is unaffected by this change")
    r = run_context(home, cwd=str(project_dir))
    chk("still exits 0", r.returncode == 0)
    chk("still shows live tickets", "live tickets" in r.stdout)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
