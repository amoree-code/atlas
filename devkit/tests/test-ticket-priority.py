#!/usr/bin/env python3
"""tests/test-ticket-priority.py — T-041: the Smart Dynamic Ticket System.

Proves the deterministic recommendation engine (`atlas_tickets.classify_and_rank`/
`explain_ticket`/`render_recommendation`) and the `atlas tickets next` /
`atlas tickets doctor` surfaces built on it: priority ordering, parent/required
relationships, owner decisions, blockers, future candidates, quick wins, goal matching,
unblocks scoring, invalid-metadata rejection, JSON output, and empty/incomplete ticket
sets. Nothing here touches the real workspace — every scenario runs against a throwaway
ATLAS_HOME/ATLAS_HOME, exactly like tests/test-tickets.py.

The one thing this file deliberately never does: assert that a *specific* score number is
correct. Scores are an internal ranking detail, not a contract — the contract is bucket
placement, relative ordering, and the presence/wording of `reasons`/`blockers`/
`confidence`, which is what every check below asserts instead.
"""
import datetime
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
    "atlas_tickets_priority_under_test", SourceFileLoader("atlas_tickets_priority_under_test", str(CLI / "atlas_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)


def make_atlas_ticket(root, project, ticket_id, state="active", extra_frontmatter="",
                       next_action="do the thing", opened_at="2026-09-06 1:00 PM",
                       updated_at="2026-09-06 1:00 PM"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
        f"project: {project}\n\nopened_at: {opened_at}\nupdated_at: {updated_at}\n\n"
        f"artifacts: []\n{extra_frontmatter}\nchecklist:\n  - \"[x] one\"\n\n"
        f"checkpoint:\n  current: in progress\n  updated_at: {updated_at}\n---\n\n"
        f"## Next action\n\n{next_action}\n"
    )
    return d


def make_index(root, project):
    (root / "projects" / project / "index.md").write_text(
        "# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")


def run_tickets(home, *args):
    return subprocess.run(
        [str(CLI / "atlas-tickets"), *args], cwd=str(home),
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def bucket_ids(buckets, name):
    return [e["id"] for e in buckets[name]]


TODAY = datetime.date(2026, 9, 6)

# =========================================================================================
t("priority ordering — Level 1 outranks Level 2, then 3, then 4")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-001", extra_frontmatter="priority: level_4\n")
    make_atlas_ticket(home, "demo", "T-002", extra_frontmatter="priority: level_1\n")
    make_atlas_ticket(home, "demo", "T-003", extra_frontmatter="priority: level_2\n")
    make_atlas_ticket(home, "demo", "T-004", extra_frontmatter="priority: level_3\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("Do now is ordered Level 1, 2, 3, 4", bucket_ids(buckets, "do_now") ==
        ["T-002", "T-003", "T-004", "T-001"])
    chk("no other bucket got anything", all(not buckets[k] for k in
        ("owner_decisions", "blocked", "paused", "quick_wins", "future")))

# =========================================================================================
t("parent and required relationships — a required child outranks an unrelated equal-priority ticket")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-010", extra_frontmatter="priority: level_2\nrelation: parent\n")
    make_atlas_ticket(home, "demo", "T-011", extra_frontmatter=(
        "priority: level_3\nparent: T-010\nrelation: required\n"))
    make_atlas_ticket(home, "demo", "T-012", extra_frontmatter="priority: level_3\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    ids = bucket_ids(buckets, "do_now")
    chk("required child (boosted) outranks a plain Level 3 with the same declared level",
        ids.index("T-011") < ids.index("T-012"))
    required_entry = next(e for e in buckets["do_now"] if e["id"] == "T-011")
    chk("reason names the parent explicitly", "required by parent T-010" in required_entry["reasons"])
    parent_entry = next(e for e in buckets["do_now"] if e["id"] == "T-010")
    chk("parent ticket's own reason says so", "is the parent ticket for this effort" in parent_entry["reasons"])

t("blocks_parent relation boosts the same way required does")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-010", extra_frontmatter="priority: level_2\nrelation: parent\n")
    make_atlas_ticket(home, "demo", "T-011", extra_frontmatter=(
        "priority: level_3\nparent: T-010\nrelation: blocks_parent\n"))
    found = tickets_mod.discover(home / "projects")
    e = tickets_mod.classify_and_rank(found)["do_now"]
    entry = next(x for x in e if x["id"] == "T-011")
    chk("blocks_parent names the parent and the closing relationship",
        "blocks parent T-010 from closing" in entry["reasons"])

# =========================================================================================
t("owner decisions — decision_required=true is placed there even when also blocked")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-020", extra_frontmatter=(
        "priority: level_1\ndecision_required: true\nblocked_by: owner\n"), state="blocked")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("lands in owner_decisions, not blocked", bucket_ids(buckets, "owner_decisions") == ["T-020"])
    chk("never appears in blocked despite blocked_by=owner", bucket_ids(buckets, "blocked") == [])
    chk("never appears in do_now", "T-020" not in bucket_ids(buckets, "do_now"))
    entry = buckets["owner_decisions"][0]
    chk("reason names the owner decision", "owner decision required" in entry["reasons"])

# =========================================================================================
t("dependency and external blockers — land in Blocked, never in Do now, reason names the blocker")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-030", extra_frontmatter="priority: level_1\nblocked_by: dependency\n")
    make_atlas_ticket(home, "demo", "T-031", extra_frontmatter="priority: level_1\nblocked_by: external\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("both blocked tickets land in Blocked", set(bucket_ids(buckets, "blocked")) == {"T-030", "T-031"})
    chk("neither appears in Do now, despite Level 1", bucket_ids(buckets, "do_now") == [])
    dep = next(e for e in buckets["blocked"] if e["id"] == "T-030")
    ext = next(e for e in buckets["blocked"] if e["id"] == "T-031")
    chk("blockers field names the dependency", dep["blockers"] == "blocked_by: dependency")
    chk("blockers field names the external blocker", ext["blockers"] == "blocked_by: external")

t("state=blocked with no blocked_by still lands in Blocked, with an honest reason")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-032", state="blocked")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    entry = buckets["blocked"][0]
    chk("blockers explains the missing reason rather than inventing one",
        entry["blockers"] == "state is blocked but 'blocked_by' is not recorded")

# =========================================================================================
t("future candidates — future_candidate relation and Level 5 both land in Future, unconditionally")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-040f", extra_frontmatter="relation: future_candidate\n")
    make_atlas_ticket(home, "demo", "T-041f", extra_frontmatter="priority: level_5\n")
    # A future candidate that is ALSO blocked and ALSO decision_required must still land
    # in Future — the strongest, most-unconditional placement rule of the five.
    make_atlas_ticket(home, "demo", "T-042f", state="blocked", extra_frontmatter=(
        "priority: level_5\nblocked_by: owner\ndecision_required: true\n"))
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("all three land in Future", set(bucket_ids(buckets, "future")) ==
        {"T-040f", "T-041f", "T-042f"})
    chk("none leak into owner_decisions despite decision_required=true",
        bucket_ids(buckets, "owner_decisions") == [])
    chk("none leak into blocked despite blocked_by=owner", bucket_ids(buckets, "blocked") == [])

# =========================================================================================
t("quick wins — small + low-risk, but never a Level 1/2 (core work is never demoted to a bonus)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-050", extra_frontmatter="priority: level_4\neffort: XS\nrisk: low\n")
    make_atlas_ticket(home, "demo", "T-051", extra_frontmatter="priority: level_1\neffort: XS\nrisk: low\n")
    make_atlas_ticket(home, "demo", "T-052", extra_frontmatter="priority: level_3\neffort: L\nrisk: low\n")
    make_atlas_ticket(home, "demo", "T-053", extra_frontmatter="priority: level_3\neffort: S\nrisk: high\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("small+low-risk Level 4 is a quick win", bucket_ids(buckets, "quick_wins") == ["T-050"])
    chk("small+low-risk Level 1 stays in Do now, not demoted", "T-051" in bucket_ids(buckets, "do_now"))
    chk("large ticket is never a quick win even if low-risk", "T-052" in bucket_ids(buckets, "do_now"))
    chk("high-risk small ticket is never a quick win", "T-053" in bucket_ids(buckets, "do_now"))

# =========================================================================================
t("goal matching — boost and reason only when --goal is given and matches")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-060", extra_frontmatter="priority: level_3\ngoal: ship the ticket system\n")
    make_atlas_ticket(home, "demo", "T-061", extra_frontmatter="priority: level_3\ngoal: unrelated cleanup\n")
    found = tickets_mod.discover(home / "projects")
    matched = tickets_mod.classify_and_rank(found, goal="ship the ticket system")
    unmatched = tickets_mod.classify_and_rank(found, goal=None)
    m60 = next(e for e in matched["do_now"] if e["id"] == "T-060")
    m61 = next(e for e in matched["do_now"] if e["id"] == "T-061")
    chk("matching ticket gets the goal reason", "matches the requested goal" in m60["reasons"])
    chk("non-matching ticket does not get the goal reason", "matches the requested goal" not in m61["reasons"])
    chk("matching ticket outranks the equal-priority non-match when a goal is given",
        m60["score"] > m61["score"])
    u60 = next(e for e in unmatched["do_now"] if e["id"] == "T-060")
    chk("no goal reason at all when --goal is omitted, even for a ticket that would match",
        "matches the requested goal" not in u60["reasons"])

# =========================================================================================
t("unblocks scoring — presence boosts and is named; a longer list does not boost without bound")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-070", extra_frontmatter="priority: level_3\n")
    make_atlas_ticket(home, "demo", "T-071", extra_frontmatter="priority: level_3\nunblocks: [T-070]\n")
    make_atlas_ticket(home, "demo", "T-072", extra_frontmatter="priority: level_3\nunblocks: [T-070, T-071]\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    e70 = next(e for e in buckets["do_now"] if e["id"] == "T-070")
    e71 = next(e for e in buckets["do_now"] if e["id"] == "T-071")
    e72 = next(e for e in buckets["do_now"] if e["id"] == "T-072")
    chk("ticket that unblocks something outranks an equal-priority ticket that unblocks nothing",
        e71["score"] > e70["score"])
    chk("unblocking two outranks or ties unblocking one (capped boost, never penalized)",
        e72["score"] >= e71["score"])
    chk("reason names exactly what is unblocked", "unblocks T-070" in e71["reasons"])
    chk("blockers is None for a ticket that is not itself blocked", e71["blockers"] is None)

# =========================================================================================
t("invalid metadata — doctor rejects every bad enum value and bad reference")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-080", extra_frontmatter=(
        "priority: level_9\nblocked_by: mars\neffort: XXL\nrisk: extreme\n"
        "confidence: sure\ndecision_required: maybe\ndue: not-a-date\nunblocks: [T-099]\n"))
    make_index(home, "demo")
    r = run_tickets(home, "doctor")
    out = r.stdout
    chk("doctor fails", r.returncode != 0)
    chk("rejects bad priority", "priority 'level_9' is not one of" in out)
    chk("rejects bad blocked_by", "blocked_by 'mars' is not one of" in out)
    chk("rejects bad effort", "effort 'XXL' is not one of" in out)
    chk("rejects bad risk", "risk 'extreme' is not one of" in out)
    chk("rejects bad confidence", "confidence 'sure' is not one of" in out)
    chk("rejects bad decision_required", "decision_required 'maybe' is not one of" in out)
    chk("rejects bad due date format", "due 'not-a-date' is not in 'YYYY-MM-DD' form" in out)
    chk("rejects a dangling unblocks reference", "unblocks references 'T-099'" in out)

t("invalid metadata — a valid ticket with the new fields passes doctor clean")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-081", extra_frontmatter=(
        "priority: level_2\nblocked_by: none\neffort: M\nrisk: medium\nconfidence: high\n"
        "decision_required: false\ndue: 2026-12-01\nlast_touched: 2026-09-06\n"
        "goal: ship it\nrequirement: REQ-081\n"))
    make_index(home, "demo")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor is clean", r.returncode == 0 and "0 error" in r.stdout)

t("blocked with no blocked_by is a doctor warning, not an error")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-082", state="blocked")
    make_index(home, "demo")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor still exits 0 (a warning, not an error)", r.returncode == 0)
    chk("warns about the missing blocked_by",
        "'blocked_by' is not recorded" in r.stdout)

t("a live ticket missing priority/goal/requirement is warned about, not rejected")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-083")
    make_index(home, "demo")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor exits 0", r.returncode == 0)
    chk("warns about missing priority", "has no 'priority' recorded" in r.stdout)
    chk("warns about missing goal", "has no 'goal' recorded" in r.stdout)
    chk("warns about missing requirement", "has no 'requirement' recorded" in r.stdout)

t("a level_5 ticket that is active is a doctor warning (future work being treated as live)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-084", extra_frontmatter="priority: level_5\n")
    make_index(home, "demo")
    run_tickets(home, "index", "--write")
    r = run_tickets(home, "doctor")
    chk("doctor still exits 0", r.returncode == 0)
    chk("warns that a level_5 ticket is active", "priority is level_5 (future) but state is 'active'" in r.stdout)

# =========================================================================================
t("JSON output — atlas tickets next --json carries every required field, all five buckets")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-090", extra_frontmatter="priority: level_2\nrelation: parent\n")
    make_index(home, "demo")
    r = run_tickets(home, "next", "--json")
    chk("exits 0", r.returncode == 0)
    data = json.loads(r.stdout)
    chk("all five buckets are always present, even with one ticket",
        set(data.keys()) == {"do_now", "owner_decisions", "blocked", "paused", "quick_wins", "future"})
    entry = data["do_now"][0]
    chk("entry carries id/title/bucket/score/priority/reasons/blockers/confidence",
        set(("id", "title", "bucket", "score", "priority", "reasons", "blockers", "confidence"))
        <= set(entry.keys()))
    chk("bucket field matches where it was placed", entry["bucket"] == "do_now")
    chk("id/title read from the ticket", entry["id"] == "T-090" and entry["title"] == "fixture T-090")

t("JSON output — --limit caps each bucket independently")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    for i in range(5):
        make_atlas_ticket(home, "demo", f"T-{100+i}", extra_frontmatter=f"priority: level_{(i % 4) + 1}\n")
    make_index(home, "demo")
    r = run_tickets(home, "next", "--json", "--limit", "2")
    data = json.loads(r.stdout)
    chk("do_now capped at 2", len(data["do_now"]) <= 2)

# =========================================================================================
t("empty and incomplete ticket sets")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-110", state="done")
    make_atlas_ticket(home, "demo", "T-111", state="cancelled")
    make_index(home, "demo")
    r = run_tickets(home, "next")
    chk("exits 0 with only done/cancelled tickets in the project", r.returncode == 0)
    chk("reports no recommendations rather than crashing or fabricating one",
        "no ticket recommendations" in r.stdout)
    rj = run_tickets(home, "next", "--json")
    data = json.loads(rj.stdout)
    chk("JSON form is all-empty buckets, not an error, not omitted keys",
        data == {"do_now": [], "owner_decisions": [], "blocked": [], "paused": [], "quick_wins": [], "future": []})

t("a ticket with none of the optional metadata still classifies without crashing")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-120")  # no priority/relation/goal/etc at all
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("lands in do_now (nothing marks it blocked/future/decision/quick-win)",
        bucket_ids(buckets, "do_now") == ["T-120"])
    entry = buckets["do_now"][0]
    chk("confidence is downgraded for the missing fields", entry["confidence"] == "low")
    chk("reasons name every missing fact instead of guessing one",
        "priority not recorded — ranked cautiously, not assumed" in entry["reasons"]
        and "no goal recorded" in entry["reasons"]
        and "no requirement recorded" in entry["reasons"])

t("due dates affect ranking but never bucket placement (never override a blocker/owner gate)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    overdue = (TODAY - datetime.timedelta(days=2)).isoformat()
    make_atlas_ticket(home, "demo", "T-130", extra_frontmatter=(
        f"priority: level_3\nblocked_by: dependency\ndue: {overdue}\n"))
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found, today=TODAY)
    chk("an overdue-but-blocked ticket still lands in Blocked, not Do now",
        bucket_ids(buckets, "blocked") == ["T-130"] and bucket_ids(buckets, "do_now") == [])
    chk("overdue is still named in reasons even while blocked",
        f"overdue since {overdue}" in buckets["blocked"][0]["reasons"])

# =========================================================================================
# T-042 regression: priority is the PRIMARY sort key. No combination of goal match,
# relation boost, unblocks or due-date urgency may ever let a lower declared level
# out-sort a higher one — only within the same declared level may they break a tie.
t("T-042 — level_2 beats level_3 even when level_3 matches the requested goal")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-200", extra_frontmatter="priority: level_3\ngoal: ship it\n")
    make_atlas_ticket(home, "demo", "T-201", extra_frontmatter="priority: level_2\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found, goal="ship it")
    chk("Level 2 (no goal match) still outranks Level 3 (goal match)",
        bucket_ids(buckets, "do_now") == ["T-201", "T-200"])

t("T-042 — level_1 beats level_4 even when level_4 is required, overdue, goal-matched, and unblocks others")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    overdue = (TODAY - datetime.timedelta(days=5)).isoformat()
    make_atlas_ticket(home, "demo", "T-210", extra_frontmatter="priority: level_1\n")
    make_atlas_ticket(home, "demo", "T-211", extra_frontmatter="priority: level_2\nrelation: parent\n")
    make_atlas_ticket(home, "demo", "T-212", extra_frontmatter=(
        f"priority: level_4\nparent: T-211\nrelation: required\ngoal: ship it\n"
        f"due: {overdue}\nunblocks: [T-210, T-211]\n"))
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found, goal="ship it", today=TODAY)
    ids = bucket_ids(buckets, "do_now")
    chk("Level 1 (no boosts at all) still outranks a maximally-boosted Level 4",
        ids.index("T-210") < ids.index("T-212"))
    entry212 = next(e for e in buckets["do_now"] if e["id"] == "T-212")
    chk("the Level 4 ticket's boosts are still visible in its own reasons/score, just "
        "not enough to cross a level boundary",
        "required by parent T-211" in entry212["reasons"]
        and "matches the requested goal" in entry212["reasons"]
        and f"overdue since {overdue}" in entry212["reasons"]
        and "unblocks T-210, T-211" in entry212["reasons"])

t("T-042 — boosts still decide ordering among tickets that share the same priority level")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-220", extra_frontmatter="priority: level_3\n")
    make_atlas_ticket(home, "demo", "T-221", extra_frontmatter="priority: level_3\ngoal: ship it\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found, goal="ship it")
    chk("same declared level: the goal-matching ticket still outranks the non-matching one",
        bucket_ids(buckets, "do_now") == ["T-221", "T-220"])

t("T-042 — a ticket with no declared priority never outranks any explicit Level 1-4 ticket")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-230", extra_frontmatter=(
        "goal: ship it\nunblocks: [T-231]\n"))  # no priority at all, but every other boost present
    make_atlas_ticket(home, "demo", "T-231", extra_frontmatter="priority: level_4\n")  # weakest real level
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found, goal="ship it")
    chk("undeclared priority (even fully boosted) still sorts after Level 4",
        bucket_ids(buckets, "do_now") == ["T-231", "T-230"])

# =========================================================================================
# T-042 regression: a paused ticket is never executable work.
t("T-042 — a paused Level 1 ticket does not appear in Do now")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-240", state="paused", extra_frontmatter="priority: level_1\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("lands in the paused bucket, not do_now, despite Level 1",
        bucket_ids(buckets, "paused") == ["T-240"] and bucket_ids(buckets, "do_now") == [])

t("T-042 — a paused XS/low-risk ticket does not appear in Quick wins")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-241", state="paused",
                       extra_frontmatter="priority: level_4\neffort: XS\nrisk: low\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("lands in paused, not quick_wins, despite being small and low-risk",
        bucket_ids(buckets, "paused") == ["T-241"] and bucket_ids(buckets, "quick_wins") == [])

t("T-042 — a paused ticket with decision_required=true still appears in Owner decisions")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-242", state="paused",
                       extra_frontmatter="priority: level_3\ndecision_required: true\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("owner decision placement wins over merely being paused",
        bucket_ids(buckets, "owner_decisions") == ["T-242"]
        and bucket_ids(buckets, "paused") == [])

t("T-042 — a paused ticket with blocked_by=dependency appears in Blocked (intentionally retained)")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-243", state="paused",
                       extra_frontmatter="priority: level_3\nblocked_by: dependency\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("an explicit blocker still surfaces in Blocked rather than being flattened into Paused",
        bucket_ids(buckets, "blocked") == ["T-243"] and bucket_ids(buckets, "paused") == [])
    chk("blockers field still names the real reason", buckets["blocked"][0]["blockers"] ==
        "blocked_by: dependency")

t("T-042 — a plain paused future_candidate still lands in Future, ahead of Paused")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-244", state="paused", extra_frontmatter="relation: future_candidate\n")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    chk("future takes precedence over paused", bucket_ids(buckets, "future") == ["T-244"]
        and bucket_ids(buckets, "paused") == [])

t("T-042 — render_recommendation shows the Paused bucket by label")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_atlas_ticket(home, "demo", "T-245", state="paused")
    found = tickets_mod.discover(home / "projects")
    buckets = tickets_mod.classify_and_rank(found)
    text = tickets_mod.render_recommendation(buckets)
    chk("'Paused' section header present", "Paused (1)" in text)
    chk("the ticket id is listed under it", "T-245" in text)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
