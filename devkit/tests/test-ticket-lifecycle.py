#!/usr/bin/env python3
"""tests/test-ticket-lifecycle.py — T-043: ticket creation and promotion.

Proves the entry gate for the Smart Dynamic Ticket System: `atlas_tickets.lifecycle_issues`/
`next_ticket_id`, and the `atlas tickets new`/`atlas tickets promote` commands built on
them. Nothing here touches the real workspace — every scenario runs against a throwaway
ATLAS_HOME/ATLAS_HOME, exactly like tests/test-tickets.py and test-ticket-priority.py.

Scope: a ticket must never be able to enter the system (via `new`) or leave the
`future_candidate` relation (via `promote`) missing priority/goal/requirement, with an
invalid enum value, or with a dangling parent/unblocks reference — refused outright,
nothing written, in every one of those cases. `promote` additionally must only ever write
a field the caller passed explicitly; nothing else about the ticket may change.
"""
import importlib.util, json, subprocess, sys, tempfile
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
    "atlas_tickets_lifecycle_under_test",
    SourceFileLoader("atlas_tickets_lifecycle_under_test", str(CLI / "atlas_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)


def make_index(root, project):
    d = root / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.md").write_text("# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")


def make_legacy_ticket(root, project, ticket_id, state="done"):
    """A pre-T-041, historical-shaped (AIOS-*) ticket — no checklist/checkpoint block,
    no intent metadata. Used to prove `next_ticket_id` ignores this generation entirely
    and that legacy tickets coexist unaffected by the lifecycle gate."""
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: legacy {ticket_id}\nstate: {state}\n"
        f"project: {project}\nopened: 2026-01-01\nupdated: 2026-01-01\n---\n\n"
        f"## Next action\n\n(none)\n"
    )
    return d


def run_tickets(home, *args):
    return subprocess.run(
        [str(CLI / "atlas-tickets"), *args], cwd=str(home),
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def read_ticket(home, project, ticket_id):
    return (home / "projects" / project / "tickets" / ticket_id / "task.md").read_text()


# =========================================================================================
t("lifecycle_issues — a fully-specified ticket has no issues")
by_id = {"T-100": {}}
issues = tickets_mod.lifecycle_issues({
    "title": "x", "state": "todo", "priority": "level_2", "goal": "g", "requirement": "r",
    "relation": "required", "parent": "T-100",
}, by_id)
chk("no issues for a complete, valid proposal", issues == [])

t("lifecycle_issues — missing priority/goal/requirement are each named")
issues = tickets_mod.lifecycle_issues({"title": "x", "state": "todo"}, {})
chk("all three required fields are named",
    any("'priority' is required" in i for i in issues)
    and any("'goal' is required" in i for i in issues)
    and any("'requirement' is required" in i for i in issues))

t("lifecycle_issues — future_candidate is exempt from the three required fields")
issues = tickets_mod.lifecycle_issues(
    {"title": "x", "state": "todo", "relation": "future_candidate"}, {})
chk("no 'is required' issues at all", not any("is required" in i for i in issues))

t("lifecycle_issues — invalid enum values are each rejected")
issues = tickets_mod.lifecycle_issues({
    "title": "x", "state": "bogus", "class": "huge", "priority": "level_9",
    "blocked_by": "mars", "effort": "XXL", "risk": "extreme", "confidence": "sure",
    "decision_required": "maybe", "due": "not-a-date", "last_touched": "also-not",
    "relation": "future_candidate",
}, {})
for needle in ("state 'bogus'", "class 'huge'", "priority 'level_9'", "blocked_by 'mars'",
              "effort 'XXL'", "risk 'extreme'", "confidence 'sure'",
              "decision_required 'maybe'", "due 'not-a-date'", "last_touched 'also-not'"):
    chk(f"rejects {needle}", any(needle in i for i in issues))

t("lifecycle_issues — relation/parent conflicts")
chk("required without parent is rejected",
    any("requires 'parent'" in i for i in
        tickets_mod.lifecycle_issues({"title": "x", "relation": "required",
                                      "priority": "level_1", "goal": "g",
                                      "requirement": "r"}, {})))
chk("parent relation must not also declare parent",
    any("must not also declare" in i for i in
        tickets_mod.lifecycle_issues({"title": "x", "relation": "parent", "parent": "T-1",
                                      "priority": "level_1", "goal": "g",
                                      "requirement": "r"}, {"T-1": {}})))
chk("a parent referencing an id that does not exist is rejected",
    any("does not match any existing ticket id" in i for i in
        tickets_mod.lifecycle_issues({"title": "x", "relation": "required", "parent": "T-999",
                                      "priority": "level_1", "goal": "g",
                                      "requirement": "r"}, {})))

t("lifecycle_issues — dangling unblocks references")
chk("an unblocks id that does not exist is rejected",
    any("unblocks references 'T-999'" in i for i in
        tickets_mod.lifecycle_issues({"title": "x", "priority": "level_1", "goal": "g",
                                      "requirement": "r", "unblocks": ["T-999"]}, {})))
chk("an unblocks id that DOES exist is accepted",
    not any("unblocks references" in i for i in
            tickets_mod.lifecycle_issues({"title": "x", "priority": "level_1", "goal": "g",
                                          "requirement": "r", "unblocks": ["T-1"]},
                                         {"T-1": {}})))

t("lifecycle_issues — missing title")
chk("empty title is rejected",
    any(i == "title is required" for i in
        tickets_mod.lifecycle_issues({"title": "  ", "priority": "level_1", "goal": "g",
                                      "requirement": "r"}, {})))

# =========================================================================================
t("next_ticket_id — starts at T-001 on an empty ticket set")
chk("T-001 for no tickets at all", tickets_mod.next_ticket_id([]) == "T-001")

t("next_ticket_id — ignores AIOS-* entirely, one continuous T-* sequence")
tix = [{"id": "AIOS-020"}, {"id": "T-005"}, {"id": "T-002"}]
chk("next is T-006, not influenced by AIOS-020", tickets_mod.next_ticket_id(tix) == "T-006")

t("next_ticket_id — archived tickets still count (never reuse a retired number)")
tix = [{"id": "T-010"}, {"id": "T-011"}]
chk("next is T-012 regardless of live/archived status",
    tickets_mod.next_ticket_id(tix) == "T-012")

# =========================================================================================
t("`atlas tickets new` — refuses with no metadata at all, nothing written")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "bare ticket",
                    "--next-action", "start")
    chk("exits nonzero", r.returncode != 0)
    chk("refused, nothing written", "refused" in r.stdout
        and not (home / "projects" / "demo" / "tickets").exists())

t("`atlas tickets new` — succeeds with complete metadata, passes doctor immediately")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "real ticket",
                    "--priority", "level_2", "--goal", "ship it", "--requirement", "REQ-1",
                    "--next-action", "start the work")
    chk("exits 0", r.returncode == 0)
    chk("created T-001 (first id in an empty project)",
        "created demo/tickets/T-001/task.md" in r.stdout)
    text = read_ticket(home, "demo", "T-001")
    chk("title/priority/goal/requirement all present in the written file",
        "title: real ticket" in text and "priority: level_2" in text
        and "goal: ship it" in text and "requirement: REQ-1" in text)
    chk("next action section present", "start the work" in text)
    d = run_tickets(home, "doctor")
    chk("doctor passes immediately, 0 errors", d.returncode == 0 and "0 error" in d.stdout)

t("`atlas tickets new` — --next-action is required even when everything else is present")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "no next action",
                    "--priority", "level_2", "--goal", "g", "--requirement", "r")
    chk("refused for missing --next-action", r.returncode != 0
        and "--next-action is required" in r.stdout)

t("`atlas tickets new` — a future_candidate ticket needs none of the three fields")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "parked idea",
                    "--relation", "future_candidate", "--next-action", "revisit later")
    chk("exits 0", r.returncode == 0)
    d = run_tickets(home, "doctor")
    chk("doctor is clean", d.returncode == 0 and "0 error" in d.stdout)

t("`atlas tickets new` — invalid metadata is refused (enum + relation/parent)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "bad", "--priority",
                    "level_2", "--goal", "g", "--requirement", "r", "--relation",
                    "required", "--next-action", "x")
    chk("required without --parent is refused by argparse-level validation path",
        r.returncode != 0 and "requires 'parent'" in r.stdout)

t("`atlas tickets new` — explicit --id collision is refused")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "first", "--priority",
               "level_2", "--goal", "g", "--requirement", "r", "--next-action", "x",
               "--id", "T-005")
    r = run_tickets(home, "new", "--project", "demo", "--title", "second", "--priority",
                    "level_2", "--goal", "g", "--requirement", "r", "--next-action", "x",
                    "--id", "T-005")
    chk("second create with the same id is refused", r.returncode != 0
        and "already exists" in r.stderr)

t("`atlas tickets new` — refuses to create inside a project that does not exist")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    (home / "projects").mkdir(parents=True)
    r = run_tickets(home, "new", "--project", "nosuchproject", "--title", "x",
                    "--priority", "level_1", "--goal", "g", "--requirement", "r",
                    "--next-action", "x")
    chk("refused, does not create the project directory either", r.returncode != 0
        and not (home / "projects" / "nosuchproject").exists())

t("`atlas tickets new` — --dry-run writes nothing")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r = run_tickets(home, "new", "--project", "demo", "--title", "dry", "--priority",
                    "level_1", "--goal", "g", "--requirement", "r", "--next-action", "x",
                    "--dry-run")
    chk("exits 0", r.returncode == 0)
    chk("nothing written", not (home / "projects" / "demo" / "tickets").exists())

t("`atlas tickets new` — coexists with a legacy AIOS-* ticket; id numbering ignores it")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    make_legacy_ticket(home, "demo", "AIOS-007")
    r = run_tickets(home, "new", "--project", "demo", "--title", "first atlas ticket",
                    "--priority", "level_1", "--goal", "g", "--requirement", "r",
                    "--next-action", "x")
    chk("gets T-001, unaffected by AIOS-007's number",
        "created demo/tickets/T-001/task.md" in r.stdout)
    d = run_tickets(home, "doctor")
    chk("doctor still passes with both generations present",
        d.returncode == 0 and "0 error" in d.stdout)

t("`atlas tickets new` — an empty project (no tickets at all yet) does not hit the "
  "'no ticket records' guard")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "brandnew")
    r = run_tickets(home, "new", "--project", "brandnew", "--title", "the very first one",
                    "--priority", "level_3", "--goal", "g", "--requirement", "r",
                    "--next-action", "x")
    chk("exits 0, not the 'no ticket records under' error", r.returncode == 0
        and "no ticket records" not in r.stderr)

t("`atlas tickets new` — a ticket referencing a legacy AIOS-* id as parent is accepted")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    make_legacy_ticket(home, "demo", "AIOS-007", state="active")
    r = run_tickets(home, "new", "--project", "demo", "--title", "child of legacy",
                    "--priority", "level_2", "--goal", "g", "--requirement", "r",
                    "--relation", "required", "--parent", "AIOS-007", "--next-action", "x")
    chk("exits 0 — a legacy id is a valid parent reference", r.returncode == 0)

# =========================================================================================
t("`atlas tickets promote` — refuses a ticket that is not future_candidate")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "already scheduled",
               "--priority", "level_2", "--goal", "g", "--requirement", "r",
               "--next-action", "x")
    r = run_tickets(home, "promote", "T-001", "--relation", "optional")
    chk("refused — nothing to promote", r.returncode != 0
        and "nothing to promote" in r.stderr)

t("`atlas tickets promote` — refuses when required metadata is still missing after the merge")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "parked", "--relation",
               "future_candidate", "--next-action", "x")
    r = run_tickets(home, "promote", "T-001", "--relation", "optional", "--priority",
                    "level_2")  # goal/requirement still missing
    chk("refused, names the still-missing fields", r.returncode != 0
        and "'goal' is required" in r.stdout and "'requirement' is required" in r.stdout)
    text = read_ticket(home, "demo", "T-001")
    chk("the ticket file is completely untouched", "relation: future_candidate" in text)

t("`atlas tickets promote` — succeeds and writes only the explicitly-passed fields")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "parent", "--priority",
               "level_1", "--goal", "root goal", "--requirement", "REQ-P",
               "--relation", "parent", "--next-action", "x")
    run_tickets(home, "new", "--project", "demo", "--title", "parked idea", "--relation",
               "future_candidate", "--effort", "M", "--next-action", "revisit")
    r = run_tickets(home, "promote", "T-002", "--relation", "required", "--parent", "T-001",
                    "--priority", "level_3", "--goal", "ship it", "--requirement", "REQ-2")
    chk("exits 0", r.returncode == 0)
    text = read_ticket(home, "demo", "T-002")
    chk("relation/parent/priority/goal/requirement all written",
        "relation: required" in text and "parent: T-001" in text
        and "priority: level_3" in text and "goal: ship it" in text
        and "requirement: REQ-2" in text)
    chk("the pre-existing, untouched --effort M from creation is still there",
        "effort: M" in text)
    chk("a log entry records the promotion",
        "promoted from future_candidate to relation=required" in text)
    d = run_tickets(home, "doctor")
    chk("doctor passes after promotion", d.returncode == 0 and "0 error" in d.stdout)

t("`atlas tickets promote` — --dry-run changes nothing")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "parent", "--priority",
               "level_1", "--goal", "g", "--requirement", "r", "--relation", "parent",
               "--next-action", "x")
    run_tickets(home, "new", "--project", "demo", "--title", "parked", "--relation",
               "future_candidate", "--next-action", "x")
    before = read_ticket(home, "demo", "T-002")
    r = run_tickets(home, "promote", "T-002", "--relation", "optional", "--parent", "T-001",
                    "--priority", "level_1", "--goal", "g", "--requirement", "r",
                    "--dry-run")
    chk("exits 0", r.returncode == 0)
    chk("file byte-identical to before", read_ticket(home, "demo", "T-002") == before)

t("`atlas tickets promote` — refuses an id that does not exist")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, "new", "--project", "demo", "--title", "x", "--priority", "level_1",
               "--goal", "g", "--requirement", "r", "--next-action", "x")
    r = run_tickets(home, "promote", "T-999", "--relation", "optional")
    chk("refused", r.returncode != 0 and "no ticket 'T-999'" in r.stderr)

t("`atlas tickets promote` — refuses to promote a legacy AIOS-* ticket (no relation field at all)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    make_legacy_ticket(home, "demo", "AIOS-007", state="todo")
    r = run_tickets(home, "promote", "AIOS-007", "--relation", "optional")
    chk("refused — relation is '(none)', not future_candidate", r.returncode != 0
        and "nothing to promote" in r.stderr)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
