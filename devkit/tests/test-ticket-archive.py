#!/usr/bin/env python3
"""tests/test-ticket-archive.py — T-024: archiving relocates, never renumbers or hides.

Everything here runs against a throwaway `projects/` tree under a temp dir, built with the
same `make_ticket` shape as `tests/test-tickets.py`. Nothing touches the real workspace.

What must hold, proven rather than assumed:
  - discover() finds a ticket whether it is live or already archived
  - archive is eligibility-only (state), never age/id-based, and moves nothing on preview
  - a plain directory move never changes task.md's bytes (hash-checked)
  - the hot per-project index drops an archived ticket; a compact archive index appears
  - next-id allocation (id_sort_key/parse_ticket_id) is unaffected by where a record sits
  - duplicate authority (same id live AND archived) is refused, not silently resolved
  - log/checkpoint refuse to mutate an archived record
"""
import hashlib
import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
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
    "atlas_tickets_archive_under_test", SourceFileLoader("atlas_tickets_archive_under_test", str(CLI / "atlas_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)


def make_ticket(root, project, ticket_id, state="done", archived_ns=None, extra=""):
    if archived_ns:
        d = root / "projects" / project / "tickets" / "archive" / archived_ns / ticket_id
    else:
        d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    is_atlas = ticket_id.startswith("T-")
    ts = ("opened_at: 2026-09-01 1:00 PM\nupdated_at: 2026-09-01 1:00 PM\n"
          "checklist:\n  - \"[x] done\"\ncheckpoint:\n  current: completed\n"
          "  updated_at: 2026-09-01 1:00 PM\n") if is_atlas else \
         "opened: 2026-09-01\nupdated: 2026-09-01\n"
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: test ticket\nstate: {state}\nproject: {project}\n"
        f"{ts}artifacts: []\n---\n\n## Objective\n\nx\n\n## Next action\n\nnone\n\n"
        f"## Verification\n\nok\n\n## Blockers\n\nnone\n\n## Log\n\n- 2026-09-01 — made\n"
        f"{extra}")
    return d


def run(*args, cwd, home):
    return subprocess.run(
        [str(CLI / "atlas-tickets"), *args], cwd=str(cwd),
        # ATLAS_HOME isolated too — `checkpoint` also writes a session-handoff pointer
        # under $ATLAS_HOME/runtime/ (atlas-context --resume); without this it would fall
        # through to the real ~/atlas instead of staying inside this fixture.
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


import tempfile

t("discover() finds a ticket whether live or archived")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_ticket(root, "demo", "T-001", state="active")
    make_ticket(root, "demo", "T-002", state="done", archived_ns="Atlas")
    make_ticket(root, "demo", "AIOS-001", state="done", archived_ns="AIOS")
    found = tickets_mod.discover(root / "projects")
    ids = {x["id"] for x in found}
    chk("live T-001 discovered", "T-001" in ids)
    chk("archived T-002 discovered", "T-002" in ids)
    chk("archived AIOS-001 discovered", "AIOS-001" in ids)
    by_id = {x["id"]: x for x in found}
    chk("live ticket is_archived is False", by_id["T-001"]["is_archived"] is False)
    chk("archived ticket is_archived is True", by_id["T-002"]["is_archived"] is True)
    chk("archive_namespace recorded for archived ticket", by_id["T-002"]["archive_namespace"] == "Atlas")
    chk("project_dir resolved correctly for a live ticket", by_id["T-001"]["project_dir"] == "demo")
    chk("project_dir resolved correctly for an archived ticket (not 'archive')",
        by_id["T-002"]["project_dir"] == "demo")

t("archive is eligibility-only: state decides, not age or id shape")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_ticket(root, "demo", "T-001", state="active")
    make_ticket(root, "demo", "T-002", state="paused")
    make_ticket(root, "demo", "T-003", state="done")
    make_ticket(root, "demo", "T-004", state="cancelled")
    make_ticket(root, "demo", "DEMO-001", state="done")  # unrecognized generation
    r = run("archive", "--project", "demo", cwd=root, home=root)
    chk("archive command runs cleanly against a synthetic workspace", r.returncode == 0)
    chk("active ticket is never proposed", "T-001" not in r.stdout)
    chk("paused ticket is never proposed", "T-002" not in r.stdout)
    chk("done ticket IS proposed", "T-003" in r.stdout)
    chk("cancelled ticket IS proposed", "T-004" in r.stdout)
    chk("a scheme outside AIOS-###/T-### is left alone even if done",
        "DEMO-001" not in r.stdout)
    chk("preview mode moves nothing", (root / "projects/demo/tickets/T-003").exists())

t("--apply moves the whole directory, byte-identical, and updates the views")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "projects" / "demo" / "index.md").write_text(
        f"# demo\n\n{tickets_mod.BEGIN}\n{tickets_mod.END}\n")
    make_ticket(root, "demo", "T-001", state="active")
    d2 = make_ticket(root, "demo", "T-002", state="done")
    (d2 / "notes.md").write_text("artifact content")
    (d2 / "task.md").write_text(
        (d2 / "task.md").read_text().replace("artifacts: []", "artifacts: [notes.md]"))
    pre_hash = hashlib.sha256((d2 / "task.md").read_bytes()).hexdigest()
    pre_notes = (d2 / "notes.md").read_text()

    r = run("archive", "--project", "demo", "--apply", cwd=root, home=root)
    chk("apply exits 0", r.returncode == 0)
    dest = root / "projects/demo/tickets/archive/Atlas/T-002"
    chk("the ticket directory now lives under archive/Atlas/", dest.exists())
    chk("the old live directory is gone", not (root / "projects/demo/tickets/T-002").exists())
    chk("task.md bytes are unchanged across the move",
        hashlib.sha256((dest / "task.md").read_bytes()).hexdigest() == pre_hash)
    chk("a beside-file artifact moved along with it", (dest / "notes.md").exists())
    chk("the artifact's own content is untouched", (dest / "notes.md").read_text() == pre_notes)
    chk("the still-active ticket was left exactly where it was",
        (root / "projects/demo/tickets/T-001").exists())
    idx = (root / "projects/demo/index.md").read_text()
    chk("the archived ticket no longer appears in the hot index", "T-002" not in idx)
    archive_idx = root / "projects/demo/tickets/archive/index.md"
    chk("a compact archive index was generated", archive_idx.exists())
    chk("the archive index names the archived ticket", "T-002" in archive_idx.read_text())
    chk("the archive index does not inline the ticket body",
        "## Objective" not in archive_idx.read_text())

t("id resolution and mutation safety after archiving")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    (root / "projects" / "demo").mkdir(parents=True)
    (root / "projects" / "demo" / "index.md").write_text(
        f"# demo\n\n{tickets_mod.BEGIN}\n{tickets_mod.END}\n")
    make_ticket(root, "demo", "T-001", state="done")
    run("archive", "--project", "demo", "--apply", cwd=root, home=root)

    r = run("log", "T-001", "trying to write to an archived ticket", cwd=root, home=root)
    chk("log refuses to mutate an archived ticket", r.returncode != 0)
    chk("the refusal names it as archived, not 'ticket not found'",
        "archived" in (r.stdout + r.stderr).lower())

    r2 = run("checkpoint", "T-001", "--note", "x", cwd=root, home=root)
    chk("checkpoint refuses to mutate an archived ticket", r2.returncode != 0)

    r3 = run("list", "--state", "done", "--project", "demo", cwd=root, home=root)
    chk("list --state done still surfaces the archived record by id", "T-001" in r3.stdout)

t("duplicate authority (same id live AND archived) is refused, not silently resolved")
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    make_ticket(root, "demo", "T-001", state="done")
    make_ticket(root, "demo", "T-001", state="done", archived_ns="Atlas")
    r = run("archive", "--project", "demo", cwd=root, home=root)
    chk("archive refuses when an id is already duplicated", r.returncode != 0)
    chk("the refusal names the duplicate id", "T-001" in (r.stdout + r.stderr))

t("id_sort_key/parse_ticket_id do not care where a record physically sits")
ids = ["AIOS-020", "T-023", "T-001"]
chk("sort order is generation-then-number regardless of live/archive location",
    sorted(ids, key=tickets_mod.id_sort_key) == ["AIOS-020", "T-001", "T-023"])


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
