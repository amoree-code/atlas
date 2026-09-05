"""aios_lifecycle — one deterministic reading of what a session should do next.

The decision is CONTINUE · CHECKPOINT · COMPACT · FRESH · HANDOFF, and this module is the
only place it is made. `ai-os lifecycle` gathers the evidence and renders it;
`ai-os usage --guard` maps its own measured findings through the same function. Two
implementations of "should this session keep going" would drift the way six copies of a
ticket's status drifted, which is the failure this whole area exists to remove.

It is pure: no filesystem, no subprocess, no clock, no model. Evidence in, decision out.
That is what makes it testable, cheap enough to run on every boundary, and explainable —
a lifecycle mechanism that cost real reasoning to consult would be self-defeating.

## No single threshold decides anything

A turn count and a context percentage are SIGNALS. The rules below require at least two
independent cost signals before context is ever called expensive, and a large context is
never discarded for being large: `unresolved_reasoning` — work in flight that still
depends on this transcript — blocks FRESH outright. Relevance, not size, is the test.

## What cannot be derived, is not guessed

Whether the user's next sentence starts a different task, whether the reasoning in flight
still matters, whether the next step is heavy disposable investigation: no filesystem
answers these, and a keyword rule dressed up as judgement would be worse than an honest
gap because it would be trusted. They arrive as explicit inputs, and their DEFAULTS are
the conservative ones — `unresolved_reasoning` defaults to True, so nothing here can
recommend throwing context away until a caller states that nothing needs it.

Zero non-stdlib dependencies. Zero dependencies inside this repository, deliberately:
`ai-os usage` imports this module, so this module must import nothing back.
"""

# Decisions.
CONTINUE = "CONTINUE"
CHECKPOINT = "CHECKPOINT"
COMPACT = "COMPACT"
FRESH = "FRESH"
HANDOFF = "HANDOFF"
DECISIONS = (CONTINUE, CHECKPOINT, COMPACT, FRESH, HANDOFF)

# Signal codes. Each names one piece of evidence, and appears in the output so a decision
# can be argued with rather than believed.
TASK_COMPLETE = "TASK_COMPLETE"
TASK_PAUSED = "TASK_PAUSED"
NEW_EXPLICIT_TICKET = "NEW_EXPLICIT_TICKET"
MILESTONE_DONE = "MILESTONE_DONE"
VERIFICATION_PASSED = "VERIFICATION_PASSED"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
NEXT_ACTION_CHANGED = "NEXT_ACTION_CHANGED"
LONG_SESSION = "LONG_SESSION"
CONTEXT_GREW_AND_NEVER_FELL = "CONTEXT_GREW_AND_NEVER_FELL"
HIGH_CONTEXT = "HIGH_CONTEXT"
HIGH_TOOL_NOISE = "HIGH_TOOL_NOISE"
ACTIVE_UNRESOLVED_REASONING = "ACTIVE_UNRESOLVED_REASONING"
HEAVY_DISPOSABLE_EXPLORATION = "HEAVY_DISPOSABLE_EXPLORATION"
HANDOFF_OPEN = "HANDOFF_OPEN"
SAFE_RECONSTRUCTION = "SAFE_RECONSTRUCTION"
NO_SAFE_RECONSTRUCTION = "NO_SAFE_RECONSTRUCTION"
NO_DURABLE_RECORD = "NO_DURABLE_RECORD"
NOT_MEASURED = "NOT_MEASURED"

# Signal thresholds. Every one of these is a REPORTING threshold: crossing it adds a
# signal, and no rule below fires on one signal alone.
LONG_SESSION_TURNS = 60      # the shape the baseline found expensive, not a limit
GROWTH_FACTOR = 4.0          # per-turn context at the end, against the first turn
COHORT_FACTOR = 2.0          # against the median of comparable sessions
TOOL_NOISE_RESULTS = 5       # large raw results admitted in one session
COST_SIGNALS_REQUIRED = 2    # never call a session expensive on one signal

# What a checkpoint carries. Durable only: this list is the contract between a session
# that ends and one that starts cold, and everything absent from it — the conversation,
# raw logs, superseded reasoning, large tool output — is what makes ending cheap.
CHECKPOINT_FIELDS = ("goal", "status", "milestone", "decisions", "changed files",
                     "evidence", "verification state", "blockers", "next action",
                     "handoff state")

# Effort by the task's declared class. The private `internal/config/models.yaml` is
# authoritative; this is the fallback for a workspace that has none, and the two are
# checked against each other by `ai-os lifecycle effort --doctor`.
EFFORT_BY_CLASS = {"small": "low", "medium": "medium", "large": "high"}
EFFORT_LADDER = ("low", "medium", "high", "xhigh", "max")

# Work whose answer is mechanical. Reasoning effort buys nothing here however large the
# surrounding task is, so the class default is overridden DOWN.
MECHANICAL_KINDS = ("grep", "path-lookup", "ticket-bookkeeping", "deterministic-command",
                    "summary", "simple-edit", "routine-test", "file-routing")

# Raising effort above the class default needs one of these, recorded. A failure count is
# not on the list: two failures are a prompt to ask why, not a reason in themselves.
ESCALATION_REASONS = ("architecture-contract-change", "security-sensitive-decision",
                      "large-blast-radius", "ambiguous-root-cause",
                      "cross-system-reasoning", "lower-effort-proved-insufficient")

DEFAULTS = {
    # Durable, from the records.
    "ticket": None,               # the live ticket's id, or None
    "has_record": False,          # a durable record exists to checkpoint into
    "task_state": None,           # active | blocked | paused | done | ...
    "task_complete": False,
    "verification": "unknown",    # passed | failed | unknown
    "milestone_done": False,
    "next_action_changed": False,
    "handoff_open": False,
    "reconstructable": False,     # a cheap packet exists NOW, without new work
    "packet_chars": None,
    # Stated by the caller, because nothing on disk knows them.
    "transition_to": None,        # another ticket the next request explicitly names
    "unresolved_reasoning": True,  # conservative: assume the transcript still decides
    "disposable_exploration": False,
    # Measured, from the client's own transcript.
    "measured": False,
    "turns": 0,
    "context_first": 0,
    "context_last": 0,
    "context_median": 0,
    "cohort_median": 0,
    "large_results": 0,
}


def evidence(**kw):
    """A complete evidence dict: the conservative defaults, with what is known applied."""
    unknown = set(kw) - set(DEFAULTS)
    if unknown:
        raise KeyError(f"unknown evidence field(s): {', '.join(sorted(unknown))}")
    ev = dict(DEFAULTS)
    ev.update({k: v for k, v in kw.items() if v is not None})
    return ev


def signals(ev):
    """Every signal the evidence supports, as (code, detail) pairs. No judgement yet."""
    out = []

    def add(code, detail):
        out.append((code, detail))

    if ev["task_complete"] or ev["task_state"] == "done":
        add(TASK_COMPLETE, "the task's work is done")
    if ev["task_state"] == "paused":
        add(TASK_PAUSED, "the record says the task is paused")
    if ev["transition_to"] and ev["transition_to"] != ev["ticket"]:
        add(NEW_EXPLICIT_TICKET, f"the next request names {ev['transition_to']}")
    if ev["milestone_done"]:
        add(MILESTONE_DONE, "a milestone landed")
    if ev["verification"] == "passed":
        add(VERIFICATION_PASSED, "verification passed since the last checkpoint")
    if ev["verification"] == "failed":
        add(VERIFICATION_FAILED, "verification is failing")
    if ev["next_action_changed"]:
        add(NEXT_ACTION_CHANGED, "the next action is no longer what the record says")
    if ev["handoff_open"]:
        add(HANDOFF_OPEN, "an open handoff record holds the state")

    if not ev["measured"]:
        add(NOT_MEASURED, "no transcript for this session was measured")
    else:
        if ev["turns"] >= LONG_SESSION_TURNS:
            add(LONG_SESSION, f"{ev['turns']} turns")
        first, last = ev["context_first"], ev["context_last"]
        if first and last > GROWTH_FACTOR * first:
            add(CONTEXT_GREW_AND_NEVER_FELL,
                f"per-turn context {first:,} -> {last:,} and never fell")
        if ev["cohort_median"] and ev["context_median"] > COHORT_FACTOR * ev["cohort_median"]:
            add(HIGH_CONTEXT,
                f"median {ev['context_median']:,} against a cohort median of "
                f"{int(ev['cohort_median']):,}")
        if ev["large_results"] >= TOOL_NOISE_RESULTS:
            add(HIGH_TOOL_NOISE, f"{ev['large_results']} large raw tool results admitted")

    if ev["unresolved_reasoning"]:
        add(ACTIVE_UNRESOLVED_REASONING, "work in flight still depends on this context")
    if ev["disposable_exploration"]:
        add(HEAVY_DISPOSABLE_EXPLORATION, "the next step is heavy disposable investigation")
    if not ev["has_record"]:
        add(NO_DURABLE_RECORD, "no ticket record to checkpoint into")
    elif ev["reconstructable"]:
        detail = "the record reconstructs cheaply"
        if ev["packet_chars"]:
            detail += f" (~{ev['packet_chars']:,} char packet)"
        add(SAFE_RECONSTRUCTION, detail)
    else:
        add(NO_SAFE_RECONSTRUCTION,
            "the record is missing a next action or verification, so a cold start "
            "would re-derive them")
    return out


def cost_signals(fired):
    """The signals that say context has become expensive. Two are required to act."""
    return [c for c in (LONG_SESSION, CONTEXT_GREW_AND_NEVER_FELL, HIGH_CONTEXT,
                        HIGH_TOOL_NOISE) if c in fired]


def decide(ev):
    """Evidence -> one decision, the sequence to run, and why. First matching rule wins.

    The order is the argument. Completion and an explicit change of workstream are
    boundaries whatever the context looks like; everything cost-driven sits below the
    guard that protects a context still being used.
    """
    sig = signals(ev)
    fired = {c for c, _ in sig}
    cost = cost_signals(fired)
    runaway = len(cost) >= COST_SIGNALS_REQUIRED
    fresh_safe = (ev["has_record"] and ev["reconstructable"]
                  and not ev["unresolved_reasoning"])

    def out(decision, sequence, why, certainty, consider=()):
        return {
            "decision": decision,
            "sequence": list(sequence),
            "why": why,
            "certainty": certainty,
            "signals": [{"code": c, "detail": d} for c, d in sig],
            "cost_signals": cost,
            "checkpoint_fields": list(CHECKPOINT_FIELDS),
            "also_consider": list(consider),
            "ticket": ev["ticket"],
            "resume_with": f"ai-os context {ev['ticket']}" if ev["ticket"] else "ai-os context",
            "fresh_recommended": FRESH in sequence,
        }

    # 1. The task is finished. Its state belongs in the record, and nothing in the
    #    transcript is worth carrying into the next one.
    if TASK_COMPLETE in fired:
        if ev["has_record"]:
            return out(FRESH, [CHECKPOINT, FRESH],
                       "the task is complete — checkpoint it and start the next one cold",
                       "deterministic")
        return out(CHECKPOINT, [CHECKPOINT],
                   "the task is complete but has no durable record; promote it before "
                   "discarding the context that holds its state",
                   "deterministic")

    # 2. A different, explicitly named workstream. Two tasks in one context is how a
    #    session ends up re-reading the first one's tail for the whole of the second.
    if NEW_EXPLICIT_TICKET in fired:
        if ev["has_record"]:
            return out(FRESH, [CHECKPOINT, FRESH],
                       f"{ev['transition_to']} is a different workstream — checkpoint "
                       f"{ev['ticket'] or 'the current task'} and start it cold",
                       "deterministic")
        return out(CHECKPOINT, [CHECKPOINT],
                   "a different workstream starts, and the current one has no record to "
                   "come back to", "deterministic")

    # 3. Heavy disposable investigation. The parent keeps its context; the worker pays
    #    for the exploration and returns a packet. This ends nothing.
    if HEAVY_DISPOSABLE_EXPLORATION in fired:
        return out(HANDOFF, [HANDOFF],
                   "isolate the investigation in a worker so its output never enters "
                   "this context", "recommended")

    # 4. Expensive by two independent signals, and safely reconstructable.
    if runaway and fresh_safe:
        return out(FRESH, [CHECKPOINT, FRESH],
                   "context has grown expensive, nothing in flight depends on it, and "
                   "the record reconstructs cheaply", "recommended")

    # 5. THE THRESHOLD GUARD. Expensive, but the context is still deciding the work.
    #    A large relevant context is not waste, and no counter overrides that.
    if runaway and ev["unresolved_reasoning"]:
        consider = [COMPACT] if HIGH_TOOL_NOISE in fired else []
        return out(CONTINUE, [CHECKPOINT] if MILESTONE_DONE in fired else [],
                   "context is large, but work in flight still depends on it — size "
                   "alone is not a reason to discard relevant context",
                   "deterministic", consider)

    # 6. A worker already holds the state, and nothing here is waiting on this transcript.
    if HANDOFF_OPEN in fired and not ev["unresolved_reasoning"] and ev["has_record"]:
        return out(FRESH, [CHECKPOINT, FRESH],
                   "an open handoff holds the state; this context is no longer the "
                   "record of it", "recommended")

    # 7. Raw tool output is the pollution, not the length. Save the durable part; the
    #    fix is `ai-os observe`, not a fresh session.
    if HIGH_TOOL_NOISE in fired:
        return out(CHECKPOINT, [CHECKPOINT],
                   "large raw tool results are most of what this context holds — "
                   "checkpoint, and run them through `ai-os observe`",
                   "recommended", [COMPACT])

    # 8. Expensive, resolved, and NOT reconstructable: compressing keeps what a cold
    #    start would have to re-derive. This is the only rule that reaches for COMPACT,
    #    which is what keeps repeated compaction from becoming the default.
    if runaway and not ev["reconstructable"]:
        return out(COMPACT, [COMPACT],
                   "context is expensive but the record cannot reconstruct it — "
                   "compress rather than lose it", "recommended")

    # 9. Durable progress that the record does not yet know about.
    if fired & {MILESTONE_DONE, VERIFICATION_PASSED, NEXT_ACTION_CHANGED, TASK_PAUSED}:
        return out(CHECKPOINT, [CHECKPOINT],
                   "durable progress the record does not yet carry", "deterministic")

    # 10. Nothing says stop.
    return out(CONTINUE, [], "the same task is in flight and its context is earning "
                             "its cost", "deterministic")


def guard_lifecycle(finding_code, has_record=True, reconstructable=True):
    """One measured guard finding -> the lifecycle reading it supports.

    `ai-os usage` measures transcripts. It cannot know whether reasoning is unresolved,
    so a growth finding maps to a CONDITIONAL recommendation and says what would settle
    it. Presenting it as a verdict would be the pretending this design refuses.
    """
    if finding_code == "grew_and_never_fell":
        if has_record and reconstructable:
            return (FRESH, "checkpoint and start cold — available once nothing in "
                           "flight depends on this transcript")
        return (CHECKPOINT, "checkpoint first: there is no packet to come back to")
    if finding_code == "above_cohort":
        return (CHECKPOINT, "carrying more than comparable sessions — checkpoint at the "
                            "next boundary")
    if finding_code == "large_results":
        return (CHECKPOINT, "run large output through `ai-os observe`, then checkpoint")
    if finding_code == "redundant_reads":
        return (CONTINUE, "re-reads cost characters, not the session — no boundary here")
    if finding_code == "strong_model_navigating":
        return (HANDOFF, "navigation belongs in a cheaper worker")
    return (CONTINUE, "no lifecycle action follows from this finding")


def effort_for(klass, kind=None, requested=None, reason=None, table=None):
    """The reasoning effort a task of this class earns, and whether it is allowed.

    Returns (effort, why, allowed). `requested` above the class default needs a named
    reason from ESCALATION_REASONS — recorded, not counted.
    """
    table = table or EFFORT_BY_CLASS
    base = table.get(klass or "", table.get("medium", "medium"))

    if kind and kind in MECHANICAL_KINDS:
        return ("low", f"{kind} is mechanical — reasoning effort buys nothing here", True)

    if not requested or requested == base:
        return (base, f"class {klass or 'unknown'} -> {base}", True)

    if requested not in EFFORT_LADDER:
        return (base, f"'{requested}' is not one of {'/'.join(EFFORT_LADDER)}", False)

    if EFFORT_LADDER.index(requested) < EFFORT_LADDER.index(base):
        return (requested, f"below the class default ({base}) — cheaper needs no reason",
                True)

    if reason in ESCALATION_REASONS:
        return (requested, f"{base} -> {requested}: {reason}", True)

    return (base, f"{requested} is above the class default ({base}) and needs a recorded "
                  f"reason: {', '.join(ESCALATION_REASONS)}", False)
