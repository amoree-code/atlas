#!/usr/bin/env python3
"""tests/test-lifecycle-engagement.py — T-023: lifecycle is engaged, not just present.

`atlas_lifecycle.decide()` has been correct and pure since before this ticket. What T-023
adds is *engagement* at boundaries (task completion, session end) and a portable
`session-handoff` output — neither of which decide() can prove by itself. This file:

  1. Benchmarks the five decisions against the scenarios named in T-023 Part I, so the
     mapping from evidence to decision has a regression test, not just a docstring.
  2. Guards against the wiring silently rotting: the boundary hook lines added to
     `task.md`/`session-end`/`catch-up`/`session-handoff` are asserted to still be
     present, so a future edit that deletes them (instead of superseding them
     deliberately) fails loudly here instead of quietly reopening the T-023 gap.
  3. Checks the `session-handoff` packet shape against its own stated size budget.

Nothing here touches the real workspace.
"""
import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli"
SKILLS = REPO / "skills"
# Resolver-driven, not hardcoded to the legacy $ATLAS_HOME path — policies has been
# Atlas-cut-over since T-030, and hardcoding here only ever worked because ~/atlas
# happened to still exist too (T-046 proved that live by quarantining it).
import subprocess as _subprocess
_policies_out = _subprocess.run([str(CLI / "atlas-paths"), "get", "policies"],
                                 capture_output=True, text=True).stdout.strip()
POLICIES = Path(_policies_out) if _policies_out else (Path.home() / "atlas" / "internal" / "governance" / "policies")

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
    "atlas_lifecycle_under_test", SourceFileLoader("atlas_lifecycle_under_test", str(CLI / "atlas_lifecycle.py")))
LC = importlib.util.module_from_spec(spec)
spec.loader.exec_module(LC)


t("Scenario 1 — same task continuation -> CONTINUE")
ev = LC.evidence(ticket="T-100", has_record=True, task_state="active",
                  unresolved_reasoning=True, measured=True, turns=10,
                  context_first=2000, context_last=3000)
d = LC.decide(ev)
chk("small in-flight session with no cost signals continues", d["decision"] == LC.CONTINUE)

t("Scenario 2 — completed task, durable update needed -> CHECKPOINT/FRESH")
ev = LC.evidence(ticket="T-100", has_record=True, task_complete=True,
                  verification="passed", reconstructable=True, unresolved_reasoning=False)
d = LC.decide(ev)
chk("a finished, reconstructable task checkpoints and goes fresh",
    d["decision"] == LC.FRESH and LC.CHECKPOINT in d["sequence"])

ev2 = LC.evidence(ticket="T-100", has_record=False, task_complete=True)
d2 = LC.decide(ev2)
chk("a finished task with no durable record checkpoints first, does not discard state",
    d2["decision"] == LC.CHECKPOINT)

t("Scenario 3 — long but still relevant session -> CONTINUE/COMPACT, never a silent FRESH")
ev = LC.evidence(ticket="T-100", has_record=True, reconstructable=True,
                  unresolved_reasoning=True, measured=True, turns=80,
                  context_first=2000, context_last=20000)
d = LC.decide(ev)
chk("expensive but still in-flight work is never thrown away", d["decision"] == LC.CONTINUE)
chk("COMPACT is offered as a consideration, not forced",
    LC.COMPACT in d["also_consider"] or LC.HIGH_TOOL_NOISE not in
    {c for c, _ in LC.signals(ev)})

t("Scenario 4 — phase boundary with low historical relevance -> FRESH")
ev = LC.evidence(ticket="T-100", has_record=True, reconstructable=True,
                  unresolved_reasoning=False, measured=True, turns=80,
                  context_first=2000, context_last=20000)
d = LC.decide(ev)
chk("expensive, resolved, and reconstructable -> FRESH",
    d["decision"] == LC.FRESH and LC.CHECKPOINT in d["sequence"])

t("Scenario 5 — move work to another Claude account/session -> HANDOFF")
ev = LC.evidence(ticket="T-100", has_record=True, disposable_exploration=True)
d = LC.decide(ev)
chk("heavy disposable investigation recommends HANDOFF", d["decision"] == LC.HANDOFF)

t("Determinism — decide() takes no clock, no filesystem, no model")
ev_a = LC.evidence(ticket="T-1", has_record=True, task_complete=True, reconstructable=True)
ev_b = LC.evidence(ticket="T-1", has_record=True, task_complete=True, reconstructable=True)
chk("identical evidence always yields an identical decision", LC.decide(ev_a) == LC.decide(ev_b))


t("Boundary wiring — TASK_COMPLETED fires from the existing 'on completion' checklist")
task_policy = (POLICIES / "task.md").read_text() if (POLICIES / "task.md").exists() else ""
chk("task.md policy exists to check", bool(task_policy))
chk("'On completion' calls atlas lifecycle, not just task-scribe/memory-curator",
    "atlas lifecycle" in task_policy and "TASK_COMPLETED" in task_policy)
chk("a HANDOFF reading routes to session-handoff, not silently ignored",
    "session-handoff" in task_policy)

t("Boundary wiring — SESSION_END_REQUEST fires from session-end")
session_end = (SKILLS / "session-end" / "SKILL.md").read_text()
chk("session-end calls atlas lifecycle before its own cleanup steps",
    "atlas lifecycle" in session_end)
chk("session-end routes HANDOFF to session-handoff", "session-handoff" in session_end)

t("catch-up prefers the derived packet over stale session records")
catch_up = (SKILLS / "catch-up" / "SKILL.md").read_text()
chk("catch-up reads atlas context before falling back to legacy session records",
    "atlas context" in catch_up)
chk("catch-up can consume a pasted session-handoff packet directly",
    "session-handoff" in catch_up)

t("session-handoff skill exists and states its own size budget")
handoff_skill_path = SKILLS / "session-handoff" / "SKILL.md"
chk("skills/session-handoff/SKILL.md exists (canonical, ai-sync renders it per client)",
    handoff_skill_path.exists())
handoff_skill = handoff_skill_path.read_text() if handoff_skill_path.exists() else ""
chk("declares it is continuation state, not a summary",
    "not a summary" in handoff_skill.lower())
chk("names a concrete size budget instead of leaving it open-ended",
    "3,000 characters" in handoff_skill or "3000 characters" in handoff_skill)
chk("explicitly excludes raw conversation/tool logs/full ticket history",
    "raw history" in handoff_skill.lower() or "tool logs" in handoff_skill.lower())
chk("carries a privacy scan step before handoff (no credentials/tokens)",
    "credentials" in handoff_skill.lower() and "tokens" in handoff_skill.lower())


t("Packet-shape benchmark — the worked example in session-handoff stays inside budget")
if handoff_skill:
    import re
    m = re.search(r"```\nProject:.*?\n```", handoff_skill, re.S)
    chk("the packet shape block is present to measure", m is not None)
    if m:
        example = m.group(0)
        chk(f"template block itself is compact ({len(example)} chars, budget ~3,000)",
            len(example) < 3000)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
