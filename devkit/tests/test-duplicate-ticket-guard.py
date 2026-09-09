#!/usr/bin/env python3
"""tests/test-duplicate-ticket-guard.py — T-100: Duplicate Ticket Guard.

Proves `atlas_tickets.normalize_keywords`/`duplicate_score`/`duplicate_candidates` and the
`atlas tickets new`/`atlas tickets watch` commands built on them: a new ticket whose title
is a likely duplicate of an existing todo/active/paused/blocked ticket is refused outright
(nothing written) unless `--force` is given together with a non-empty `--reason`; `watch` is
the same scoring, read-only. Deterministic keyword overlap only — no AI or vector
dependency, so every score in this file is exact and reproducible. Nothing here touches the
real workspace — every scenario runs against a throwaway ATLAS_HOME/ATLAS_HOME, exactly
like tests/test-ticket-lifecycle.py.
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
    "atlas_tickets_duplicate_guard_under_test",
    SourceFileLoader("atlas_tickets_duplicate_guard_under_test", str(CLI / "atlas_tickets.py")))
tickets_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tickets_mod)


def make_index(root, project):
    d = root / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.md").write_text("# demo\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n")


def run_tickets(home, *args):
    return subprocess.run(
        [str(CLI / "atlas-tickets"), *args], cwd=str(home),
        env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )


def new_args(title, **extra):
    args = ["new", "--project", "demo", "--title", title, "--priority", "level_1",
           "--goal", "g", "--requirement", "r", "--next-action", "x"]
    for k, v in extra.items():
        args += [f"--{k.replace('_', '-')}", v] if v is not True else [f"--{k}"]
    return args


# =========================================================================================
t("normalize_keywords — lowercase, tokenized, stopwords dropped")
chk("stopwords removed, case-folded", tickets_mod.normalize_keywords("Fix the Login Form")
    == {"fix", "login", "form"})
chk("empty title yields an empty set", tickets_mod.normalize_keywords("") == set())
chk("None title yields an empty set, does not crash", tickets_mod.normalize_keywords(None) == set())
chk("a title that is only stopwords yields an empty set",
    tickets_mod.normalize_keywords("The Of And") == set())

t("duplicate_score — Jaccard similarity, 0.0 when either side is empty")
chk("identical keyword sets score 1.0",
    tickets_mod.duplicate_score({"a", "b"}, {"a", "b"}) == 1.0)
chk("disjoint sets score 0.0",
    tickets_mod.duplicate_score({"a", "b"}, {"c", "d"}) == 0.0)
chk("partial overlap scores the exact Jaccard ratio",
    tickets_mod.duplicate_score({"a", "b", "c"}, {"b", "c", "d"}) == 2 / 4)
chk("an empty side scores 0.0, never divides by zero",
    tickets_mod.duplicate_score(set(), {"a"}) == 0.0
    and tickets_mod.duplicate_score({"a"}, set()) == 0.0)

# =========================================================================================
t("duplicate_candidates — only CANDIDATE_STATES tickets are scored, never done/cancelled/archived")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Duplicate Ticket Guard for creation"))
    run_tickets(home, *new_args("Completely unrelated cleanup"))
    run_tickets(home, "checkpoint", "T-002", "--note", "done", "--state", "done")
    tickets = tickets_mod.discover(home / "projects")
    cands = tickets_mod.duplicate_candidates("Duplicate Ticket Guard for creation", tickets,
                                             exclude_id="T-001")
    ids = [c[0]["id"] for c in cands]
    chk("the done ticket (T-002, unrelated title anyway) is not a false concern here",
        "T-002" not in ids)
    chk("no candidates at all once the only other ticket is unrelated and done", ids == [])

t("duplicate_candidates — a done ticket sharing the exact same title is excluded")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Ship the release notes page"))
    run_tickets(home, "checkpoint", "T-001", "--note", "shipped", "--state", "done")
    tickets = tickets_mod.discover(home / "projects")
    cands = tickets_mod.duplicate_candidates("Ship the release notes page", tickets)
    chk("a done ticket is never a duplicate candidate, even with an identical title",
        cands == [])

# =========================================================================================
t("`atlas tickets new` — a near-identical title is refused, nothing written")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    r1 = run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    chk("first ticket is created", r1.returncode == 0 and "created" in r1.stdout)
    r2 = run_tickets(home, *new_args("Duplicate ticket detection for ticket creation"))
    chk("near-duplicate is refused", r2.returncode != 0)
    chk("refusal names the candidate and the override", "T-001" in r2.stdout
        and "--force --reason" in r2.stdout)
    chk("no second ticket directory was written",
        not (home / "projects" / "demo" / "tickets" / "T-002").exists())

t("`atlas tickets new` — --force without --reason still refuses")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, *new_args("Duplicate ticket detection for ticket creation",
                                    force=True))
    chk("still refused: --force alone is not an override", r.returncode != 0)
    chk("still nothing written",
        not (home / "projects" / "demo" / "tickets" / "T-002").exists())

t("`atlas tickets new` — --force --reason overrides the guard and writes the ticket")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, *new_args("Duplicate ticket detection for ticket creation",
                                    force=True, reason="different scope, tracked separately"))
    chk("override succeeds", r.returncode == 0 and "created" in r.stdout)
    chk("the second ticket now exists",
        (home / "projects" / "demo" / "tickets" / "T-002").exists())

t("`atlas tickets new` — an unrelated title is never blocked")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, *new_args("Rewrite the onboarding email templates"))
    chk("unrelated title creates cleanly", r.returncode == 0 and "created" in r.stdout)

t("`atlas tickets new` — a low-similarity title (below the high-confidence line) is not blocked")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Duplicate Ticket Guard for new tickets"))
    r = run_tickets(home, *new_args("Guard against duplicate tickets"))
    chk("below-threshold overlap is allowed through", r.returncode == 0
        and "created" in r.stdout)

# =========================================================================================
t("`atlas tickets watch` — previews the same scoring, read-only, text form")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, "watch", "--title", "Duplicate ticket detection for ticket creation")
    chk("exits 0", r.returncode == 0)
    chk("names the matching ticket and its score", "T-001" in r.stdout and "score" in r.stdout)
    chk("flags it as a likely duplicate `new` would refuse",
        "would refuse" in r.stdout)
    chk("nothing was written by watch",
        not (home / "projects" / "demo" / "tickets" / "T-002").exists())

t("`atlas tickets watch` — JSON form carries id/title/state/score/matches_on")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, "watch", "--title", "Duplicate ticket detection for ticket creation",
                    "--json")
    chk("exits 0", r.returncode == 0)
    data = json.loads(r.stdout)
    chk("exactly one candidate", len(data) == 1)
    entry = data[0]
    chk("carries id/title/state/score/matches_on",
        set(("id", "title", "state", "score", "matches_on")) <= set(entry.keys()))
    chk("id is the existing ticket", entry["id"] == "T-001")

t("`atlas tickets watch` — no candidates reports cleanly, not an error")
with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp)
    make_index(home, "demo")
    run_tickets(home, *new_args("Add duplicate ticket detection to ticket creation"))
    r = run_tickets(home, "watch", "--title", "Something entirely unrelated")
    chk("exits 0", r.returncode == 0)
    chk("reports no match rather than fabricating one",
        "no live ticket shares a keyword" in r.stdout)
    rj = run_tickets(home, "watch", "--title", "Something entirely unrelated", "--json")
    chk("JSON form is an empty list, not an error", json.loads(rj.stdout) == [])

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
