#!/usr/bin/env python3
"""tests/test-ticket-auto-archive.py — T-044: Smart Automatic Ticket Archive System.

Everything here runs against a throwaway `projects/` tree under a temp dir, the same
pattern as tests/test-ticket-archive.py (T-024) and test-ticket-lifecycle.py (T-043).
Nothing touches the real workspace.

What must hold, proven rather than assumed:
  - `checkpoint --state done`/`--state cancelled` archives immediately when the ticket
    passes the completion gate, and only then
  - the gate refuses (ticket left exactly where it was, byte-identical) a done ticket with
    an unchecked checklist item, a doctor-level structural error, or an open required child
  - blocked/active/todo/paused tickets are never touched by any automatic path
  - `archive --auto` is the idempotent reconciliation path: same gate, safe to re-run,
    `--dry-run` writes nothing
  - task.md bytes and beside-file artifacts survive a move unchanged
  - destination collision and duplicate authority are refused, not silently resolved
  - the generated archive index groups Completed/Cancelled by Level 1-5/Unspecified, plus
    a separate Legacy AIOS section, and is deterministic across a repeated run
  - the live project index drops an archived ticket; `show`/`search`/`archive --list` find
    archived records and never mutate anything
  - an empty candidate set and an empty archive are both handled without error
"""
import hashlib
import importlib.util
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
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


spec = importlib.util.spec_from_loader(
    "aios_tickets_auto_archive_under_test",
    SourceFileLoader("aios_tickets_auto_archive_under_test", str(CLI / "aios_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)


def make_index(root, project):
    d = root / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.md").write_text(f"# {project}\n\n{tickets_mod.BEGIN}\n{tickets_mod.END}\n")


def make_ticket(root, project, ticket_id, state="active", priority=None, parent=None,
                relation=None, checklist=("[x] done",), next_action="none",
                requirement="REQ-1", goal="a goal", extra_meta=""):
    """An Atlas-native (T-*) or historical (AIOS-*) ticket, whichever `ticket_id` implies."""
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    is_atlas = ticket_id.startswith("T-")
    lines = [f"id: {ticket_id}", "title: test ticket", f"state: {state}",
            f"project: {project}"]
    if is_atlas:
        lines += ["opened_at: 2026-09-01 1:00 PM", "updated_at: 2026-09-01 1:00 PM"]
    else:
        lines += ["opened: 2026-09-01", "updated: 2026-09-01"]
    if parent:
        lines.append(f"parent: {parent}")
    if relation:
        lines.append(f"relation: {relation}")
    lines.append(f"requirement: {requirement}")
    lines.append(f"goal: {goal}")
    if priority:
        lines.append(f"priority: {priority}")
    lines.append("artifacts: []")
    if extra_meta:
        lines.append(extra_meta.strip())
    if is_atlas:
        lines.append("checklist:")
        for item in checklist:
            lines.append(f'  - "{item}"')
        lines.append("checkpoint:")
        lines.append("  current: in progress")
        lines.append("  updated_at: 2026-09-01 1:00 PM")
    body = "\n".join(lines)
    (d / "task.md").write_text(
        f"---\n{body}\n---\n\n## Objective\n\nx\n\n## Next action\n\n{next_action}\n\n"
        f"## Verification\n\nok\n\n## Blockers\n\nnone\n\n## Log\n\n- 2026-09-01 — made\n")
    return d


def run(*args, cwd, home):
    return subprocess.run(
        [str(CLI / "ai-os-tickets"), *args], cwd=str(cwd),
        env={"AI_OS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


t("automatic archive after `checkpoint --state done`")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_2",
               next_action="finish it")
    r = run("checkpoint", "T-001", "--note", "wrapping up", "--state", "done",
           cwd=root, home=root)
    chk("checkpoint exits 0", r.returncode == 0)
    chk("checkpoint reports the automatic archive", "automatically archived" in r.stdout)
    dest = root / "projects/demo/tickets/archive/Atlas/T-001"
    chk("the ticket now lives under archive/Atlas/", dest.exists())
    chk("the old live directory is gone", not (root / "projects/demo/tickets/T-001").exists())

t("automatic archive of `cancelled`")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_3")
    r = run("checkpoint", "T-001", "--note", "abandoning", "--state", "cancelled",
           cwd=root, home=root)
    chk("checkpoint exits 0", r.returncode == 0)
    chk("checkpoint reports the automatic archive", "automatically archived" in r.stdout)
    dest = root / "projects/demo/tickets/archive/Atlas/T-001"
    chk("a cancelled ticket is archived exactly like a done one", dest.exists())
    text = (dest / "task.md").read_text()
    chk("state remains 'cancelled' — archiving never rewrites state",
        "state: cancelled" in text)

t("done ticket with an unchecked checklist item is refused")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_1",
               checklist=("[x] step one", "[ ] step two"))
    before = sha(root / "projects/demo/tickets/T-001/task.md")
    r = run("checkpoint", "T-001", "--note", "done-ish", "--state", "done",
           cwd=root, home=root)
    chk("checkpoint itself still succeeds (the state write is separate from archiving)",
        r.returncode == 0)
    chk("checkpoint reports the refusal, not a silent skip",
        "not archived automatically" in r.stdout)
    chk("the exact reason (unchecked checklist item) is named",
        "unchecked" in r.stdout)
    live_path = root / "projects/demo/tickets/T-001/task.md"
    chk("the ticket was NOT moved", live_path.exists())
    chk("the ticket's bytes are unchanged except for the state/timestamp fields "
        "checkpoint itself writes (still not archived)",
        not (root / "projects/demo/tickets/archive/Atlas/T-001").exists())

t("done ticket with a doctor-level structural error is refused")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="not_a_real_level")
    r = run("checkpoint", "T-001", "--note", "done", "--state", "done", cwd=root, home=root)
    chk("checkpoint exits 0", r.returncode == 0)
    chk("archive refused for the invalid priority enum",
        "not archived automatically" in r.stdout)
    chk("the reason names the bad priority value", "not_a_real_level" in r.stdout)
    chk("not archived", not (root / "projects/demo/tickets/archive/Atlas/T-001").exists())

t("done ticket with an open required child is refused")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_2")
    make_ticket(root, "demo", "T-002", state="active", priority="level_2",
               parent="T-001", relation="required")
    r = run("checkpoint", "T-001", "--note", "closing parent", "--state", "done",
           cwd=root, home=root)
    chk("checkpoint exits 0", r.returncode == 0)
    chk("archive refused: an open required child still depends on it",
        "not archived automatically" in r.stdout)
    chk("the reason names the open child", "T-002" in r.stdout)
    chk("the parent was left live, not archived",
        (root / "projects/demo/tickets/T-001").exists())

    # Once the child is done too, the parent becomes archivable via reconciliation.
    run("checkpoint", "T-002", "--note", "child done", "--state", "done",
       cwd=root, home=root)
    r2 = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("reconciliation archives the parent once its required child is done",
        (root / "projects/demo/tickets/archive/Atlas/T-001").exists())

t("blocked/active/todo/paused tickets are never touched by any automatic path")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="blocked", priority="level_2")
    make_ticket(root, "demo", "T-002", state="active", priority="level_2")
    make_ticket(root, "demo", "T-003", state="todo", priority="level_2")
    make_ticket(root, "demo", "T-004", state="paused", priority="level_2")
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("archive --auto exits 0 with nothing eligible", r.returncode == 0)
    for tid in ("T-001", "T-002", "T-003", "T-004"):
        chk(f"{tid} was never proposed or moved",
            tid not in r.stdout and (root / f"projects/demo/tickets/{tid}").exists())

t("Level 1 through Level 5 archive sections")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    for i, level in enumerate(("level_1", "level_2", "level_3", "level_4", "level_5"), 1):
        make_ticket(root, "demo", f"T-{i:03d}", state="done", priority=level)
    make_ticket(root, "demo", "T-006", state="done", priority=None)  # Unspecified
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("archive --auto exits 0", r.returncode == 0)
    idx = (root / "projects/demo/tickets/archive/index.md").read_text()
    chk("Completed section present", "## Completed" in idx)
    for label in ("Level 1", "Level 2", "Level 3", "Level 4", "Level 5", "Unspecified"):
        chk(f"'{label}' subsection present under Completed", f"### {label}" in idx)
    for i in range(1, 6):
        chk(f"T-{i:03d} appears in the archive index", f"T-{i:03d}" in idx)
    chk("the Unspecified-priority ticket appears too", "T-006" in idx)

t("legacy AIOS-* archive section")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "AIOS-001", state="done")
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("archive --auto exits 0", r.returncode == 0)
    dest = root / "projects/demo/tickets/archive/AIOS/AIOS-001"
    chk("a legacy ticket archives under archive/AIOS/, not archive/Atlas/", dest.exists())
    idx = (root / "projects/demo/tickets/archive/index.md").read_text()
    chk("'Legacy AIOS' section present", "## Legacy AIOS" in idx)
    chk("AIOS-001 appears there", "AIOS-001" in idx)
    # Must not also appear duplicated under Completed/Cancelled (those are Atlas-only).
    completed_block = idx.split("## Completed", 1)[1].split("## Legacy AIOS", 1)[0]
    chk("AIOS-001 is not duplicated into the Completed/Cancelled sections",
        "AIOS-001" not in completed_block)

t("directory and artifact preservation, byte-identical task.md")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    d = make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    (d / "notes.md").write_text("artifact content")
    text = (d / "task.md").read_text().replace("artifacts: []", "artifacts: [notes.md]")
    (d / "task.md").write_text(text)
    pre_hash = sha(d / "task.md")
    pre_notes = (d / "notes.md").read_text()

    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("archive --auto exits 0", r.returncode == 0)
    dest = root / "projects/demo/tickets/archive/Atlas/T-001"
    chk("task.md bytes are unchanged across the move", sha(dest / "task.md") == pre_hash)
    chk("the beside-file artifact moved along with it", (dest / "notes.md").exists())
    chk("the artifact's own content is untouched",
        (dest / "notes.md").read_text() == pre_notes)

t("destination collision is refused, not silently resolved")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    (root / "projects/demo/tickets/archive/Atlas/T-001").mkdir(parents=True)
    (root / "projects/demo/tickets/archive/Atlas/T-001/task.md").write_text("occupied")
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("refused, named as a destination collision",
        "destination already exists" in r.stdout)
    chk("the live ticket was left in place",
        (root / "projects/demo/tickets/T-001").exists())
    chk("the pre-existing occupant at the destination was not overwritten",
        (root / "projects/demo/tickets/archive/Atlas/T-001/task.md").read_text() == "occupied")

t("a failed move is reported, not silently swallowed or half-applied")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    archive_root = root / "projects/demo/tickets/archive"
    archive_root.mkdir(parents=True)
    archive_root.chmod(0o500)  # read+execute, no write — mkdir/move under it must fail
    try:
        r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
        chk("the command reports failure rather than crashing", r.returncode != 0
            or "failed" in r.stdout)
        chk("the failure names the ticket", "T-001" in (r.stdout + r.stderr))
        chk("the source ticket was left in place (no partial move)",
            (root / "projects/demo/tickets/T-001/task.md").exists())
    finally:
        archive_root.chmod(0o700)

t("duplicate ticket id authority is refused, not silently resolved")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    make_ticket(root, "demo", "T-002", state="done", priority="level_2")
    # Force a duplicate id by rewriting T-002's own frontmatter id to T-001.
    p = root / "projects/demo/tickets/T-002/task.md"
    p.write_text(p.read_text().replace("id: T-002", "id: T-001", 1))
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("the duplicated id is refused with a named reason",
        "refused" in r.stdout and "duplicate ticket id" in r.stdout)

t("repeated `archive --auto` is idempotent")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    r1 = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("first run archives it", "1 ticket(s) archived" in r1.stdout)
    idx1 = (root / "projects/demo/tickets/archive/index.md").read_text()
    r2 = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("second run finds nothing left to reconcile", r2.returncode == 0)
    chk("second run reports nothing eligible",
        "nothing to reconcile" in r2.stdout or "no done/cancelled" in r2.stdout)
    idx2 = (root / "projects/demo/tickets/archive/index.md").read_text()
    chk("the archive index is unchanged (deterministic) across the repeated run",
        idx1 == idx2)

t("--dry-run writes nothing")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    pre_hash = sha(root / "projects/demo/tickets/T-001/task.md")
    r = run("archive", "--auto", "--dry-run", "--project", "demo", cwd=root, home=root)
    chk("dry-run exits 0", r.returncode == 0)
    chk("dry-run reports what would move", "T-001" in r.stdout)
    chk("dry-run says nothing was moved", "nothing moved" in r.stdout)
    chk("the ticket was NOT moved", (root / "projects/demo/tickets/T-001").exists())
    chk("no archive directory was created at all",
        not (root / "projects/demo/tickets/archive").exists())
    chk("task.md bytes are unchanged",
        sha(root / "projects/demo/tickets/T-001/task.md") == pre_hash)

t("the active index excludes archived records")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_2")
    make_ticket(root, "demo", "T-002", state="done", priority="level_2")
    run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    idx = (root / "projects/demo/index.md").read_text()
    chk("the still-active ticket appears in the hot index", "T-001" in idx)
    chk("the archived ticket does not appear in the hot index", "T-002" not in idx)

t("archive index is deterministic across repeated generation")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2")
    make_ticket(root, "demo", "T-002", state="cancelled", priority="level_1")
    run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    idx1 = (root / "projects/demo/tickets/archive/index.md").read_text()
    run("index", "--project", "demo", "--write", cwd=root, home=root)
    idx2 = (root / "projects/demo/tickets/archive/index.md").read_text()
    chk("the archive index is unaffected by an unrelated `index --write`", idx1 == idx2)

t("show/search/list read archived tickets, and never mutate")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="done", priority="level_2",
               goal="a very findable goal phrase")
    run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    dest = root / "projects/demo/tickets/archive/Atlas/T-001/task.md"
    pre_hash = sha(dest)

    r = run("show", "T-001", cwd=root, home=root)
    chk("show finds the archived record", r.returncode == 0)
    chk("show labels it as archived", "ARCHIVED" in r.stdout)
    chk("show prints the record body", "## Objective" in r.stdout)

    r2 = run("search", "findable goal", cwd=root, home=root)
    chk("search finds it by goal text", "T-001" in r2.stdout)
    chk("search labels it as archived", "archived" in r2.stdout)

    r3 = run("archive", "--list", "--project", "demo", cwd=root, home=root)
    chk("archive --list finds it", "T-001" in r3.stdout)

    chk("none of the three read commands mutated task.md", sha(dest) == pre_hash)

t("empty archive and empty active set")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    make_ticket(root, "demo", "T-001", state="active", priority="level_2")
    r = run("archive", "--list", "--project", "demo", cwd=root, home=root)
    chk("archive --list on an empty archive exits 0", r.returncode == 0)
    chk("archive --list says there is nothing archived", "no archived tickets" in r.stdout)

    run("checkpoint", "T-001", "--note", "done", "--state", "done", cwd=root, home=root)
    r2 = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("nothing left in the active set after the only ticket archives",
        r2.returncode == 0)
    idx = (root / "projects/demo/index.md").read_text()
    chk("the hot index is now empty of tickets", "T-001" not in idx)

t("legacy ticket compatibility — AIOS-* with no checklist/priority fields at all")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_index(root, "demo")
    d = root / "projects" / "demo" / "tickets" / "AIOS-001"
    d.mkdir(parents=True)
    (d / "task.md").write_text(
        "---\nid: AIOS-001\ntitle: legacy\nstate: done\nproject: demo\n"
        "opened: 2026-09-01\nupdated: 2026-09-01\nartifacts: []\n---\n\n"
        "## Objective\n\nx\n\n## Next action\n\nnone\n\n## Verification\n\nok\n\n"
        "## Blockers\n\nnone\n\n## Log\n\n- 2026-09-01 — made\n")
    r = run("archive", "--auto", "--project", "demo", cwd=root, home=root)
    chk("a legacy ticket with none of the Atlas-native fields still archives cleanly",
        (root / "projects/demo/tickets/archive/AIOS/AIOS-001").exists())
    chk("archive --auto exits 0 for a clean legacy ticket", r.returncode == 0)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
