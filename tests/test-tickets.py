#!/usr/bin/env python3
"""tests/test-tickets.py — T-001: two ticket-id generations, one tooling layer.

`AIOS-###` (historical, frozen at AIOS-020) and `T-###` (Atlas-native, starting at T-001)
are unrelated identities that must both work everywhere the ticket tooling touches an id:
parsing, sorting, `list`, `index`, `doctor`, `log`/`checkpoint` lookup. Nothing here touches
the real workspace — every scenario runs against a throwaway `ATLAS_HOME`.
"""
import importlib.util, subprocess, sys, tempfile
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
    "atlas_tickets_under_test", SourceFileLoader("atlas_tickets_under_test", str(CLI / "atlas_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)

sys.path.insert(0, str(CLI))
spec2 = importlib.util.spec_from_loader(
    "atlas_tickets_cli_under_test", SourceFileLoader("atlas_tickets_cli_under_test", str(CLI / "atlas-tickets")))
cli_mod = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(cli_mod)


def make_ticket(root, project, ticket_id, state="active", extra_frontmatter="",
                 next_action="do the thing"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
        f"project: {project}\nopened: 2026-09-05\nupdated: 2026-09-05\n{extra_frontmatter}"
        f"---\n\n## Next action\n\n{next_action}\n"
    )
    return d


def make_atlas_ticket(root, project, ticket_id, state="done", checklist=None,
                       opened_at="2026-09-05 2:00 PM", updated_at="2026-09-05 2:00 PM",
                       checkpoint_current="completed", next_action="", extra_frontmatter=""):
    """A ticket in the full Atlas-native metadata shape: opened_at/updated_at, then
    checklist, then checkpoint last — the shape this ticket (T-001) itself finalizes."""
    checklist = checklist if checklist is not None else ['"[x] one thing done"']
    items = "\n".join(f"  - {c}" for c in checklist)
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
        f"project: {project}\n\nopened_at: {opened_at}\nupdated_at: {updated_at}\n\n"
        f"artifacts: []\n{extra_frontmatter}\nchecklist:\n{items}\n\n"
        f"checkpoint:\n  current: {checkpoint_current}\n  updated_at: {updated_at}\n---\n\n"
        f"## Next action\n\n{next_action}\n"
    )
    return d


def run_tickets(home, *args):
    return subprocess.run(
        [str(CLI / "atlas-tickets"), *args], cwd=str(home),
        # ATLAS_HOME is isolated too: `checkpoint` also generates a session-handoff
        # pointer under $ATLAS_HOME/runtime/ (see atlas-context --resume) — without this,
        # every checkpoint call in this file would silently fall through to the real
        # ~/atlas and write a real pointer from fixture data. Caught by running this
        # exact suite after that feature was added, not by inspection.
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


# =========================================================================================
t("parse_ticket_id — valid ids")
chk("AIOS-001 parses as Generation 1", tickets_mod.parse_ticket_id("AIOS-001") == ("AIOS", 1))
chk("AIOS-020 parses as Generation 1", tickets_mod.parse_ticket_id("AIOS-020") == ("AIOS", 20))
chk("T-001 parses as Atlas-native", tickets_mod.parse_ticket_id("T-001") == ("T", 1))
chk("T-999 parses as Atlas-native", tickets_mod.parse_ticket_id("T-999") == ("T", 999))
chk("T-1000 parses (numeric, not padded to 3)", tickets_mod.parse_ticket_id("T-1000") == ("T", 1000))

t("parse_ticket_id — malformed ids rejected")
for bad in ("T-1", "T-01", "T1", "T-", "T-abc", "t-001", "AIOS-1", "AIOS-01", "AIOS1",
            "AIOS-abc", "aios-001", "X-001", "", None, "T -001", "T-001 "):
    chk(f"{bad!r} is not a valid ticket id", tickets_mod.parse_ticket_id(bad) is None)

t("AIOS-001 and T-001 are distinct identities")
chk("different generations", tickets_mod.parse_ticket_id("AIOS-001")[0]
    != tickets_mod.parse_ticket_id("T-001")[0])
chk("not equal as ids", "AIOS-001" != "T-001")
chk("do not share a sort key", tickets_mod.id_sort_key("AIOS-001") != tickets_mod.id_sort_key("T-001"))

# =========================================================================================
t("id_sort_key — generation-aware ordering, not accidental lexical order")
ids = ["T-999", "AIOS-020", "T-002", "AIOS-001", "T-001", "AIOS-010"]
ordered = sorted(ids, key=tickets_mod.id_sort_key)
chk("historical block sorts before Atlas-native block, each internally numeric",
    ordered == ["AIOS-001", "AIOS-010", "AIOS-020", "T-001", "T-002", "T-999"])

chk("numeric order beats lexical order across widths (T-2 before T-10)",
    sorted(["T-010", "T-002"], key=tickets_mod.id_sort_key) == ["T-002", "T-010"])

malformed_key = tickets_mod.id_sort_key("not-an-id")
chk("a malformed id sorts after every recognized generation",
    malformed_key > tickets_mod.id_sort_key("T-999") and malformed_key > tickets_mod.id_sort_key("AIOS-020"))

# =========================================================================================
t("discover() — mixed generations, one project")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_ticket(home, "demo", "AIOS-001")
    make_ticket(home, "demo", "AIOS-020")
    make_ticket(home, "demo", "T-001")
    make_ticket(home, "demo", "T-999")
    found = tickets_mod.discover(home / "projects")
    ids = sorted(x["id"] for x in found)
    chk("all four fixture tickets discovered", ids == ["AIOS-001", "AIOS-020", "T-001", "T-999"])
    by_id = {x["id"]: x for x in found}
    chk("AIOS-001 and T-001 loaded as separate records, not merged",
        by_id["AIOS-001"]["path"] != by_id["T-001"]["path"])
    chk("T-001 read its own frontmatter correctly", by_id["T-001"]["title"] == "fixture T-001")

# =========================================================================================
t("atlas-tickets list — mixed generations")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_ticket(home, "demo", "AIOS-001")
    make_ticket(home, "demo", "AIOS-020")
    make_ticket(home, "demo", "T-001")
    r = run_tickets(home, "list")
    chk("list exits 0", r.returncode == 0)
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith(("AIOS-", "T-"))]
    order = [l.split()[0] for l in lines]
    chk("list orders AIOS- before T-, both listed", order == ["AIOS-001", "AIOS-020", "T-001"])

# =========================================================================================
t("atlas-tickets doctor — backward compatible, T-* valid, id format stays unenforced")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_ticket(home, "demo", "AIOS-001", state="done", next_action="")
    make_ticket(home, "demo", "AIOS-020", state="done", next_action="")
    make_atlas_ticket(home, "demo", "T-001")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    r = run_tickets(home, "doctor")
    chk("doctor exits nonzero before index is written (stale table)", r.returncode != 0)
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor passes with historical + Atlas-native tickets, index current",
        r.returncode == 0 and "0 error" in r.stdout)

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    # Doctor's structural checks (id == dir name, required fields, artifact manifest) are
    # deliberately id-format-agnostic: a project can use its own scheme (DEMO-*, as the
    # rest of this suite's contract tests do) and that must keep working unmodified — T-*
    # recognition is additive, not a new global constraint on what an id may look like.
    make_atlas_ticket(home, "demo", "T-001")
    make_ticket(home, "demo", "DEMO-CUSTOM-1", state="done", next_action="")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    r = run_tickets(home, "doctor")
    chk("doctor exits nonzero only because the index is stale, not the id shape",
        r.returncode != 0 and "not a recognized" not in r.stdout)
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor stays clean with a non-generation project-scoped id alongside T-*",
        r.returncode == 0 and "0 error" in r.stdout)

# =========================================================================================
t("atlas-tickets checkpoint/log — T-* lookup works exactly like AIOS-*")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-001", state="active",
                       updated_at="2020-01-01 1:00 AM", next_action="original action")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    r = run_tickets(home, "log", "T-001", "progress noted")
    chk("log accepts a T-* id", r.returncode == 0)
    r = run_tickets(home, "checkpoint", "T-001", "--note", "landed a slice", "--next", "next slice")
    chk("checkpoint accepts a T-* id", r.returncode == 0)
    text = (home / "projects" / "demo" / "tickets" / "T-001" / "task.md").read_text()
    chk("checkpoint rewrote T-001's Next action", "next slice" in text)
    chk("checkpoint appended T-001's log", "landed a slice" in text)
    top_level_updated_at = [l for l in text.splitlines() if l.startswith("updated_at:")][0]
    chk("checkpoint/log bumped the top-level updated_at to a fresh readable timestamp",
        "2020-01-01 1:00 AM" not in top_level_updated_at
        and bool(tickets_mod.TIMESTAMP_RE.match(top_level_updated_at.partition(":")[2].strip())))
chk("the checkpoint block's own current/updated_at is untouched (out of scope by design)",
        "current: completed" in text and "2020-01-01 1:00 AM" in text)

# =========================================================================================
t("ticket intent layer — parent/extension/future metadata")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-040", state="active",
                       extra_frontmatter="class: large\nrelation: parent\ngoal: unify the product\n",
                       next_action="approve the first slice")
    make_atlas_ticket(home, "demo", "T-041", state="todo",
                       extra_frontmatter=("class: small\nparent: T-040\nrelation: optional\n"
                                          "requirement: REQ-040\n"),
                       next_action="")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor accepts a parent ticket and optional child relation",
        r.returncode == 0 and "0 error" in r.stdout)
    idx = (home / "projects" / "demo" / "index.md").read_text()
    chk("generated index exposes the role column",
        "| ID | State | Class | Role | Title | Next action | Record |" in idx)
    chk("generated index shows optional child under its parent",
        "optional of T-040" in idx)
    loaded = {t["id"]: t for t in tickets_mod.discover(home / "projects")}
    chk("reader carries goal/parent/relation metadata for callers",
        loaded["T-040"]["goal"] == "unify the product"
        and loaded["T-041"]["parent"] == "T-040"
        and loaded["T-041"]["relation"] == "optional")

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-040", state="active",
                       extra_frontmatter="class: large\nrelation: parent\n",
                       next_action="approve")
    make_atlas_ticket(home, "demo", "T-041", state="todo",
                       extra_frontmatter="class: small\nrelation: optional\n",
                       next_action="")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor rejects an optional child with no parent",
        r.returncode != 0 and "requires frontmatter 'parent'" in r.stdout)

# =========================================================================================
t("no collision between AIOS-001 and T-001 in the same project")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_ticket(home, "demo", "AIOS-001", state="active", next_action="historical action")
    make_ticket(home, "demo", "T-001", state="active", next_action="atlas action")
    (home / "projects" / "demo" / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")
    r = run_tickets(home, "checkpoint", "T-001", "--note", "touch only T-001")
    chk("checkpoint exits 0", r.returncode == 0)
    atlas_text = (home / "projects" / "demo" / "tickets" / "AIOS-001" / "task.md").read_text()
    chk("AIOS-001's record is untouched by a T-001 checkpoint", "touch only T-001" not in atlas_text)
    chk("AIOS-001 keeps its own next action", "historical action" in atlas_text)

# =========================================================================================
t("required_fields_for — AIOS-* keeps opened/updated, T-* requires opened_at/updated_at")
chk("AIOS-* still requires the legacy pair",
    set(tickets_mod.required_fields_for("AIOS-001")) >= {"opened", "updated"}
    and "opened_at" not in tickets_mod.required_fields_for("AIOS-001"))
chk("T-* requires the readable-timestamp pair instead",
    set(tickets_mod.required_fields_for("T-001")) >= {"opened_at", "updated_at"}
    and "opened" not in tickets_mod.required_fields_for("T-001"))
chk("an unrecognized id (e.g. DEMO-*) falls back to the legacy pair, unchanged",
    tickets_mod.required_fields_for("DEMO-001") == tickets_mod.REQUIRED)

# =========================================================================================
t("atlas_metadata_issues — the canonical T-001 shape is clean")
GOOD_ATLAS = (
    "---\nid: T-900\ntitle: x\nstate: done\nproject: atlas\n\n"
    "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:39 PM\n\n"
    "artifacts: []\nclass: small\n\n"
    "checklist:\n  - \"[x] did the thing\"\n  - \"[x] verified it\"\n\n"
    "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:39 PM\n---\n\nbody\n"
)
meta, _ = tickets_mod.parse_frontmatter(GOOD_ATLAS)
chk("no issues on the canonical shape",
    tickets_mod.atlas_metadata_issues(GOOD_ATLAS, meta, "T-900") == [])

t("atlas_metadata_issues — catches each rule it's supposed to")


def issues_for(frontmatter_body, state="done"):
    text = f"---\nid: T-901\ntitle: x\nstate: {state}\nproject: atlas\n{frontmatter_body}---\n\nbody\n"
    meta, _ = tickets_mod.parse_frontmatter(text)
    return tickets_mod.atlas_metadata_issues(text, meta, "T-901")


chk("missing checklist/checkpoint entirely is flagged",
    any("require both" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n")))

chk("checkpoint before checklist (wrong order) is flagged",
    any("last frontmatter field" in i or "immediately precede" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[x] a\"\n")))

chk("a trailing field after checkpoint is flagged (checkpoint must be last)",
    any("last frontmatter field" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[x] a\"\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n"
        "extra: field\n")))

chk("a malformed checkbox marker ([X] upper-case) is flagged",
    any("malformed checklist item" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[X] a\"\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n")))

chk("a bare, unquoted checklist line is flagged",
    any("malformed checklist item" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - [x] a\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n")))

chk("single-quoted historical checklist is accepted",
    not issues_for("opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
                   "checklist:\n  - '[x] completed'\n"
                   "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n"))

chk("state: done with an unchecked item is flagged",
    any("is unchecked" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[ ] a\"\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n",
        state="done")))

chk("the same unchecked item is fine while state is active",
    not any("is unchecked" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[ ] a\"\n"
        "checkpoint:\n  current: in progress\n  updated_at: 2026-09-05 2:00 PM\n",
        state="active")))

chk("a checkpoint block missing 'current' is flagged",
    any("missing 'current'" in i for i in issues_for(
        "opened_at: 2026-09-05 2:00 PM\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[x] a\"\n"
        "checkpoint:\n  updated_at: 2026-09-05 2:00 PM\n")))

chk("an unreadable opened_at (not h:mm AM/PM) is flagged",
    any("not in" in i for i in issues_for(
        "opened_at: 2026-09-05T14:00:00Z\nupdated_at: 2026-09-05 2:00 PM\n"
        "checklist:\n  - \"[x] a\"\n"
        "checkpoint:\n  current: completed\n  updated_at: 2026-09-05 2:00 PM\n")))

# =========================================================================================
t("now_readable — matches the canonical format, local time not UTC")
chk("now_readable() matches YYYY-MM-DD h:mm AM/PM",
    bool(tickets_mod.TIMESTAMP_RE.match(cli_mod.now_readable())))

t("bump_updated — targets updated_at when present, updated: otherwise")
atlas_text = "---\nid: T-902\nupdated_at: 2020-01-01 1:00 AM\n---\nbody\n"
bumped = cli_mod.bump_updated(atlas_text, "2026-09-05")
chk("updated_at is replaced with a fresh readable timestamp",
    "2020-01-01 1:00 AM" not in bumped and "updated_at:" in bumped)
legacy_text = "---\nid: AIOS-902\nupdated: 2020-01-01\n---\nbody\n"
bumped_legacy = cli_mod.bump_updated(legacy_text, "2026-09-05")
chk("updated: (legacy) is replaced with the plain date, unchanged behavior",
    "updated: 2026-09-05" in bumped_legacy)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
