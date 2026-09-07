"""aios_tickets — reading the durable ticket records, for Python callers.

One implementation of "what does this ticket say", used by `ai-os tickets` and by
`ai-os context`. Two readers of the same records is how two views of one status start
disagreeing, which is the failure this whole area exists to remove.

It reads. It never writes, moves or deletes a record.
Zero non-stdlib dependencies.
"""
import datetime
import re
from pathlib import Path

STATES = ("todo", "active", "paused", "blocked", "done", "cancelled")
LIVE = ("active", "blocked")
REQUIRED = ("id", "title", "state", "project", "opened", "updated")
CLASSES = ("small", "medium", "large")
SCOPES = ("small", "medium", "large")
RELATIONS = ("parent", "required", "optional", "blocks_parent", "future_candidate")

# --- Smart Dynamic Ticket System metadata (T-041, corrected T-042) ------------------------
# Priority is a declared fact, never a computed guess: a level is only ever read from a
# ticket's own frontmatter, never assigned by ranking logic.
#
# Two separate numbers exist here, on purpose, for two separate jobs — conflating them was
# the T-042 bug (a Level 3 ticket with enough boosts could out-sort a boost-free Level 1):
#
#   PRIORITY_RANK   the ONLY thing that decides ordering ACROSS declared levels. Level 1
#                   (rank 0) always sorts before Level 2 (rank 1), which always sorts before
#                   Level 3, and so on — no score, boost or combination of boosts can move a
#                   ticket across a rank boundary. This is the primary key of the sort tuple
#                   `classify_and_rank` builds; nothing else in this module is allowed to be
#                   compared before it.
#   PRIORITY_WEIGHT the same relative ordering, expressed as a `score` contribution — kept
#                   only so `score`/`reasons` stay useful for *explaining* a recommendation
#                   and for breaking ties WITHIN one declared level (goal match, relation,
#                   unblocks, due date). `score` is a secondary sort key, read only after
#                   `PRIORITY_RANK` already agrees; it must never be compared on its own
#                   across two tickets that declared different levels.
#
# `MISSING_PRIORITY_RANK`/`MISSING_PRIORITY_WEIGHT` are deliberately not one of the five real
# values — a ticket with no declared priority must never rank exactly where a real Level 3/4
# ticket would, or a missing fact would look indistinguishable from a stated one. Both sit
# strictly between Level 4 and Level 5 (rank 3.5, weight 30), so undeclared work is ranked
# cautiously — below every explicitly declared Level 1-4 ticket, never above one — without
# impersonating any real level; the gap is also surfaced in `reasons` and in `confidence`.
PRIORITIES = ("level_1", "level_2", "level_3", "level_4", "level_5")
PRIORITY_RANK = {"level_1": 0, "level_2": 1, "level_3": 2, "level_4": 3, "level_5": 4}
MISSING_PRIORITY_RANK = 3.5
PRIORITY_WEIGHT = {"level_1": 100, "level_2": 80, "level_3": 60, "level_4": 40, "level_5": 20}
MISSING_PRIORITY_WEIGHT = 30
RELATION_BOOST = {"blocks_parent": 15, "required": 15, "parent": 10,
                  "optional": 0, "future_candidate": 0}
BLOCKED_BY = ("none", "owner", "dependency", "dirty_state", "external")
EFFORTS = ("XS", "S", "M", "L")
# Quick wins are small AND low-risk — both, not either; a small-but-risky or a
# low-risk-but-large ticket is core work, not a quick win, and stays out of this bucket.
QUICK_WIN_EFFORTS = ("XS", "S")
RISKS = ("low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")
CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}
CONFIDENCE_LABEL = {0: "low", 1: "medium", 2: "high"}
BOOLEANS = ("true", "false")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Fields whose absence on live work is reported (doctor warning) and lowers the
# recommendation's confidence (never its priority — see PRIORITY_WEIGHT above).
CONFIDENCE_FIELDS = ("priority", "goal", "requirement")
BEGIN = "<!-- ai-os:tickets:begin -->"
END = "<!-- ai-os:tickets:end -->"
# Soft reporting thresholds. Nothing is refused for crossing one; they exist so a record
# that has quietly turned into a transcript is visible before a cold read pays for it.
SOFT_NEXT_ACTION_CHARS = 400
SOFT_LOG_ENTRIES = 20
SOFT_TASK_BYTES = 12000

# --- ticket id generations ---------------------------------------------------------------
# Two generations of ticket id are live at once, and neither is going away:
#   AIOS-###  Generation 1, historical, immutable — AIOS-001 .. AIOS-020 and frozen there.
#   T-###     Atlas-native, starting at T-001 (personal/knowledge/decisions/
#             atlas-one-project-architecture.md item 6).
# They are unrelated identities forever — AIOS-001 and T-001 do not alias, collide, or
# compare equal — so this is two patterns recognized side by side, never one pattern with a
# variable prefix. Both require a zero-padded number of at least 3 digits, matching the
# convention already in use (AIOS-001, not AIOS-1); T-### is free to grow past 999.
GENERATION_PATTERNS = {
    "AIOS": re.compile(r"^AIOS-(\d{3,})$"),
    "T": re.compile(r"^T-(\d{3,})$"),
}
# Sort order between generations: historical stays a block before Atlas-native, so the
# existing AIOS-001..AIOS-020 ordering is undisturbed by anything sorting alongside it.
#
# This is a SORT preference only, not a validation gate: a project is free to use its own
# id scheme (a fixture in tests/test-contract.sh uses DEMO-###, and a real project may use
# its own registry key) and that must keep working, unmodified, forever — doctor does not
# call parse_ticket_id and never rejects an id for not being AIOS-* or T-*.
GENERATION_ORDER = {"AIOS": 0, "T": 1}


def parse_ticket_id(ticket_id):
    """(generation, number) for an id in one of the two ai-os/Atlas ticket generations,
    or None for anything else — including a perfectly valid id in some other project's own
    scheme, which this deliberately does not try to recognize.

    A ticket id belongs to exactly one generation or none — never both, never a fallback
    guess. Case-sensitive: ids are written upper-case by convention, and a lower-case id is
    treated as unrecognized rather than silently normalized.
    """
    if not ticket_id:
        return None
    for generation, pattern in GENERATION_PATTERNS.items():
        m = pattern.match(ticket_id)
        if m:
            return generation, int(m.group(1))
    return None


def id_sort_key(ticket_id):
    """Deterministic sort key: generation first (AIOS before T), then numeric order.

    Numeric, not lexical — T-999 sorts before a future T-1000 either way, which a plain
    string compare would get backwards. An id that fails to parse sorts last, after every
    known generation, rather than silently interleaving with either.
    """
    parsed = parse_ticket_id(ticket_id)
    if parsed is None:
        return (len(GENERATION_ORDER), 0, ticket_id or "")
    generation, number = parsed
    return (GENERATION_ORDER[generation], number, ticket_id)


# --- Atlas-native ticket metadata shape ---------------------------------------------------
# Owner decision: an Atlas-native (`T-*`) ticket's frontmatter carries a `checklist` and a
# `checkpoint` block, in that order, both required, `checkpoint` always last — the record
# separates what the ticket IS (identity/status/timestamps) from where execution currently
# STANDS (checkpoint). Historical `AIOS-*` tickets are never held to this shape; only a `T-*`
# id is checked. Timestamps are workspace-local wall-clock time, human readable, no stored
# timezone per ticket (see internal/config/settings.yaml `timezone: auto`).
ATLAS_TIMESTAMP_FIELDS = ("opened_at", "updated_at")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{1,2}:\d{2} (AM|PM)$")
CHECKBOX_RE = re.compile(r'^-\s+"\[( |x)\]\s+.+"\s*$')


def required_fields_for(ticket_id):
    """REQUIRED, with the timestamp pair swapped for the id's generation.

    Historical tickets keep `opened`/`updated`. A `T-*` id requires `opened_at`/`updated_at`
    instead — the two schemes are never both required and never both optional on one ticket.
    """
    generation = parse_ticket_id(ticket_id)
    if generation and generation[0] == "T":
        return tuple(f for f in REQUIRED if f not in ("opened", "updated")) + ATLAS_TIMESTAMP_FIELDS
    return REQUIRED


def frontmatter_block(text):
    """Raw frontmatter lines, indentation intact, or None when there is no `---` block.

    `parse_frontmatter` above throws indentation away on purpose (it only wants top-level
    scalars); validating `checklist`/`checkpoint` needs the nested lines back.
    """
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    return text[4:end].splitlines()


def atlas_metadata_issues(text, meta, ticket_id):
    """Structural problems in a `T-*` ticket's frontmatter, as a list of strings.

    Checked only for a `T-*` id — call sites are expected to gate on `parse_ticket_id`
    themselves; this does not re-check the generation. Whitespace around values is always
    stripped before comparison, so reindenting the YAML block does not trip these checks.
    """
    issues = []
    lines = frontmatter_block(text)
    if lines is None:
        return [f"{ticket_id}: has no frontmatter block"]

    for field in ATLAS_TIMESTAMP_FIELDS:
        value = meta.get(field)
        if value and not TIMESTAMP_RE.match(value):
            issues.append(f"{ticket_id}: '{field}: {value}' is not in "
                          f"'YYYY-MM-DD h:mm AM/PM' form")

    top_level = [(i, line[:line.index(":")].strip())
                 for i, line in enumerate(lines)
                 if line and line[0] not in " \t#" and ":" in line]
    keys_in_order = [k for _, k in top_level]

    if "checklist" not in keys_in_order or "checkpoint" not in keys_in_order:
        issues.append(f"{ticket_id}: Atlas-native tickets require both a 'checklist' and "
                      f"a 'checkpoint' block")
        return issues
    if keys_in_order[-1] != "checkpoint":
        issues.append(f"{ticket_id}: 'checkpoint' must be the last frontmatter field")
    if keys_in_order[-2] != "checklist":
        issues.append(f"{ticket_id}: 'checklist' must immediately precede 'checkpoint'")

    checklist_line = next(i for i, k in top_level if k == "checklist")
    checkpoint_line = next(i for i, k in top_level if k == "checkpoint")

    unchecked = False
    for line in lines[checklist_line + 1:checkpoint_line]:
        stripped = line.strip()
        if not stripped:
            continue
        if not CHECKBOX_RE.match(stripped):
            issues.append(f"{ticket_id}: malformed checklist item: {stripped!r} "
                          f"(expected '- \"[ ] ...\"' or '- \"[x] ...\"')")
        elif "[ ]" in stripped:
            unchecked = True
    if meta.get("state") == "done" and unchecked:
        issues.append(f"{ticket_id}: state is 'done' but a checklist item is unchecked")

    checkpoint_body = [l.strip() for l in lines[checkpoint_line + 1:] if l.strip()]
    if not any(l.startswith("current:") for l in checkpoint_body):
        issues.append(f"{ticket_id}: 'checkpoint' block is missing 'current'")
    ts_line = next((l for l in checkpoint_body if l.startswith("updated_at:")), None)
    if ts_line is None:
        issues.append(f"{ticket_id}: 'checkpoint' block is missing 'updated_at'")
    else:
        ts_value = ts_line.partition(":")[2].strip().strip('"')
        if not TIMESTAMP_RE.match(ts_value):
            issues.append(f"{ticket_id}: checkpoint 'updated_at: {ts_value}' is not in "
                          f"'YYYY-MM-DD h:mm AM/PM' form")

    return issues


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta, rest = {}, text[end + 4:]
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep or line.startswith((" ", "\t", "#")):
            continue
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            value = [v.strip() for v in inner.split(",") if v.strip()] if inner else []
        meta[key.strip()] = value
    return meta, rest


def section(body, heading):
    """The text under one `## heading`, up to the next `## `."""
    m = re.search(rf"^## {re.escape(heading)}\s*$", body, re.M)
    if not m:
        return None
    rest = body[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return (rest[:nxt.start()] if nxt else rest).strip()


def first_line(text):
    for line in (text or "").splitlines():
        line = line.strip().lstrip("*").strip()
        if line and not line.startswith(("<!--", "```")):
            return line
    return ""


# T-024: a ticket record no longer has to live at `tickets/<ID>/task.md` — a `done`/
# `cancelled` one may have been moved, whole, to `tickets/archive/<NAMESPACE>/<ID>/task.md`
# by `ai-os tickets archive`. `archive/` is a container, never itself a ticket id, and
# nothing under it is written by anything but that one command. `ARCHIVE_DIRNAME` is the
# single name every reader/writer agrees on, so it is defined once, here.
ARCHIVE_DIRNAME = "archive"


def load(path, projects_root=None):
    text = path.read_text()
    meta, body = parse_frontmatter(text)
    na = section(body, "Next action") or ""
    log = section(body, "Log") or ""
    # project_dir is "the first path segment under projects_root" regardless of how many
    # directories separate it from task.md — true for both `<project>/tickets/<ID>/task.md`
    # (2 segments in between) and an archived `<project>/tickets/archive/<NS>/<ID>/task.md`
    # (4 segments in between). Falling back to the old fixed-depth read when no
    # projects_root is given keeps every existing caller working unchanged.
    if projects_root is not None:
        rel_parts = path.relative_to(projects_root).parts
        project_dir = rel_parts[0]
        is_archived = len(rel_parts) > 4 and rel_parts[1] == "tickets" and rel_parts[2] == ARCHIVE_DIRNAME
        archive_namespace = rel_parts[3] if is_archived else None
    else:
        project_dir = path.parent.parent.parent.name
        is_archived = False
        archive_namespace = None
    return {
        "path": str(path),
        "dir": str(path.parent),
        "dir_name": path.parent.name,
        "project_dir": project_dir,
        "is_archived": is_archived,
        "archive_namespace": archive_namespace,
        "meta": meta,
        "id": meta.get("id"),
        "title": meta.get("title", ""),
        "state": meta.get("state", ""),
        "project": meta.get("project", ""),
        "klass": meta.get("class"),
        "expected_context": meta.get("expected_context"),
        "classification": meta.get("classification"),
        "parent": meta.get("parent"),
        "requirement": meta.get("requirement"),
        "relation": meta.get("relation"),
        "decision_required": meta.get("decision_required"),
        "goal": meta.get("goal"),
        "priority": meta.get("priority"),
        "blocked_by": meta.get("blocked_by"),
        "unblocks": meta.get("unblocks") if isinstance(meta.get("unblocks"), list) else (
            [meta["unblocks"]] if meta.get("unblocks") else []),
        "effort": meta.get("effort"),
        "risk": meta.get("risk"),
        "confidence": meta.get("confidence"),
        "due": meta.get("due"),
        "last_touched": meta.get("last_touched"),
        "updated": meta.get("updated", ""),
        "artifacts": meta.get("artifacts") if isinstance(meta.get("artifacts"), list) else [],
        "next_action": na,
        "next_action_line": first_line(na),
        "log_entries": len([l for l in log.splitlines() if l.startswith("- ")]),
        "bytes": len(text),
    }


def discover(projects_root, project=None):
    """Every ticket record, live or archived. One glob per location, one reader.

    Live: `<project>/tickets/<ID>/task.md`. Archived: `<project>/tickets/archive/<NS>/<ID>/
    task.md`. A record's physical location never changes what it IS — every caller that
    wants "is this in the way right now" reads `is_archived`/`state`, not the path.
    """
    out = []
    patterns = ("*/tickets/*/task.md", f"*/tickets/{ARCHIVE_DIRNAME}/*/*/task.md")
    for pattern in patterns:
        for task in sorted(projects_root.glob(pattern)):
            t = load(task, projects_root)
            if project and t["project_dir"] != project:
                continue
            out.append(t)
    return out


# --- Smart Dynamic Ticket System — deterministic recommendation engine (T-041) ------------
# One implementation, same reason the rest of this module is one implementation: `ai-os
# tickets next` and `ai-os context`'s recommended-next-actions view must never compute two
# different answers for "what should happen next" from the same records. Everything below
# reads declared metadata; nothing here decides a priority, a goal, or a relationship that
# the ticket itself did not already state — a gap is reported (low confidence, a `reasons`
# line), never filled in.
#
# `done`/`cancelled` tickets and archived records are not candidates for "what's next" —
# there is nothing left to recommend about finished or retired work. `paused` IS still a
# candidate state — a paused ticket is still tracked, still reportable, and still able to
# surface as an Owner decision or a Blocked entry — but it is never executable work: see
# `classify_and_rank`'s `paused` bucket, which keeps a merely-paused ticket (T-042) out of
# Do now and Quick wins specifically, regardless of its priority, effort or risk.
CANDIDATE_STATES = ("todo", "active", "paused", "blocked")


def _priority_rank(priority):
    """The PRIMARY sort key: 0 (Level 1, best) through 4 (Level 5), or 3.5 for an
    undeclared priority — strictly worse than every declared Level 1-4 and strictly
    better than Level 5. Nothing computed elsewhere in this module (score, boosts) may
    ever be compared before this value; see the module-level comment above
    `PRIORITY_RANK` for why the two numbers were split apart."""
    return PRIORITY_RANK.get(priority, MISSING_PRIORITY_RANK)


def _priority_weight(priority):
    """A SECONDARY, explanatory number only — same relative ordering as `_priority_rank`,
    expressed as a `score` contribution so `reasons`/`score` stay human-readable and so
    boosts can still break ties within one declared level. Never used to order tickets
    across two different declared levels; `classify_and_rank` sorts on `_priority_rank`
    first, always, and only reads `score` to break a tie within the same rank."""
    return PRIORITY_WEIGHT.get(priority, MISSING_PRIORITY_WEIGHT)


def _confidence(t):
    """The ticket's own declared confidence, discounted one step per missing field in
    `CONFIDENCE_FIELDS` (priority/goal/requirement) — never raised above what was declared,
    never invented when nothing was declared (an undeclared confidence starts at the
    neutral middle, 'medium', then still takes the same discount as a declared one)."""
    declared = CONFIDENCE_RANK.get(t.get("confidence"), 1)
    missing = sum(1 for f in CONFIDENCE_FIELDS if not t.get(f))
    return CONFIDENCE_LABEL[max(0, declared - missing)]


def _goal_match(t, goal):
    """True only when both sides actually have text and one contains the other,
    case-insensitively. No match at all (never a boost, never a penalty) when the caller
    passed no `--goal`, or the ticket recorded none — matching nothing to nothing is not
    evidence of relevance."""
    if not goal or not t.get("goal"):
        return False
    a, b = goal.strip().lower(), t["goal"].strip().lower()
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def _urgency(due, today):
    """'overdue', 'soon' (due within 7 days inclusive), or None — for a missing or
    malformed `due`, None: an unparsable date is a doctor-reported problem, not a ranking
    signal to guess at."""
    if not due or not DATE_RE.match(due):
        return None
    try:
        d = datetime.date.fromisoformat(due)
    except ValueError:
        return None
    delta = (d - today).days
    if delta < 0:
        return "overdue"
    if delta <= 7:
        return "soon"
    return None


def explain_ticket(t, goal, today):
    """One ticket's score, bucket signals and human-readable reasons — the single place
    both `ai-os tickets next` and `ai-os context`'s next-actions view get an answer from,
    so the two can never disagree. Returns a dict with the internal bucket signals still
    present under `_future`/`_decision_required`/`_is_blocked`/`_paused`/`_quick_win`;
    `classify_and_rank` consumes and removes them before a caller ever sees this record.
    The returned `priority` field (not an internal one — it is part of the public shape)
    is what `classify_and_rank` derives its PRIMARY sort key from via `_priority_rank`;
    `score` here is explanatory and secondary only, never compared across two different
    declared priority levels."""
    priority = t.get("priority")
    relation = t.get("relation")
    parent = t.get("parent")
    blocked_by = t.get("blocked_by")
    unblocks = t.get("unblocks") or []
    decision_required = (t.get("decision_required") or "").strip().lower() == "true"
    due = t.get("due")

    reasons = []
    if priority in PRIORITY_WEIGHT:
        reasons.append(priority.replace("_", " ").title())
    else:
        reasons.append("priority not recorded — ranked cautiously, not assumed")

    if relation == "required" and parent:
        reasons.append(f"required by parent {parent}")
    elif relation == "blocks_parent" and parent:
        reasons.append(f"blocks parent {parent} from closing")
    elif relation == "parent":
        reasons.append("is the parent ticket for this effort")
    elif relation == "optional" and parent:
        reasons.append(f"optional relative to {parent}")
    elif relation == "future_candidate":
        reasons.append("recorded as a future candidate, not scheduled work")

    goal_matched = _goal_match(t, goal)
    if goal_matched:
        reasons.append("matches the requested goal")
    elif not t.get("goal"):
        reasons.append("no goal recorded")

    if not t.get("requirement"):
        reasons.append("no requirement recorded")

    if unblocks:
        reasons.append(f"unblocks {', '.join(unblocks)}")

    urgency = _urgency(due, today)
    if urgency == "overdue":
        reasons.append(f"overdue since {due}")
    elif urgency == "soon":
        reasons.append(f"due soon ({due})")

    if decision_required:
        reasons.append("owner decision required")

    is_blocked = t.get("state") == "blocked" or bool(blocked_by and blocked_by != "none")
    blockers = None
    if is_blocked:
        blockers = (f"blocked_by: {blocked_by}" if blocked_by and blocked_by != "none"
                    else "state is blocked but 'blocked_by' is not recorded")
        reasons.append(blockers)

    score = (_priority_weight(priority)
             + RELATION_BOOST.get(relation, 0)
             + (25 if goal_matched else 0)
             + min(5 * len(unblocks), 15)
             + {"overdue": 10, "soon": 5}.get(urgency, 0))

    return {
        "id": t["id"],
        "title": t.get("title") or "",
        "score": score,
        "priority": priority,
        "reasons": reasons,
        "blockers": blockers,
        "confidence": _confidence(t),
        "_future": relation == "future_candidate" or priority == "level_5",
        "_decision_required": decision_required,
        "_is_blocked": is_blocked,
        "_paused": t.get("state") == "paused",
        # A quick win is small AND low-risk AND not already core/critical work — Level 1/2
        # stays ranked (and shown) as core work no matter how small it is, so a critical
        # ticket can never be quietly outranked by being filed as a "bonus" instead.
        "_quick_win": (t.get("effort") in QUICK_WIN_EFFORTS and t.get("risk") == "low"
                       and priority not in ("level_1", "level_2")),
    }


def classify_and_rank(tickets, goal=None, today=None):
    """Deterministic bucket + score for every non-archived, non-terminal ticket in `tickets`.

    Bucket precedence — a ticket lands in exactly one bucket, first match wins:

      1. Future           relation=future_candidate OR priority=level_5. An explicit
                           "not on the current execution path" signal outranks every other
                           fact about the ticket, including being blocked or owner-gated —
                           a future idea does not need re-litigating as a blocker just
                           because it also happens to have one recorded.
      2. Owner decisions   decision_required=true. The classification contract states this
                           placement unconditionally, so it is checked before Blocked and
                           before Paused: a decision-gated ticket must surface as a
                           decision, not disappear into a generic blocked or paused bucket
                           instead — true even for a ticket whose `state` is `paused`.
      3. Blocked           state=blocked, or blocked_by names a real reason (not 'none').
                           Checked before Paused for the same reason: a paused ticket that
                           is ALSO explicitly blocked (blocked_by=dependency, say) still
                           needs its blocker surfaced, not buried under "just paused".
                           Never appears in Do now or Quick wins, by construction — this
                           check happens before either is reachable.
      4. Paused           state=paused, and none of the above matched. A paused ticket is
                           not executable work: it must never appear in Do now or Quick
                           wins (T-042) purely because it happens to be small, low-risk, or
                           high priority — pausing is itself the reason it is not "now".
      5. Quick wins        effort in (XS, S) AND risk=low AND not Level 1/2 (see
                           `explain_ticket`'s `_quick_win` comment). A paused ticket never
                           reaches this check — see Paused above.
      6. Do now            everything else live and actionable. A paused ticket never
                           reaches this check either.

    Sort key within each bucket — `(_priority_rank, -score, id)`, in that order:

      `_priority_rank` is compared FIRST and ALONE decides ordering across two different
      declared priority levels: Level 1 always sorts before Level 2, Level 2 always before
      Level 3, and so on, and an undeclared priority always sorts after every declared
      Level 1-4 (T-042 — a prior version let goal/relation/unblocks/due boosts add up to
      more than one level's worth of `score` and let a lower level out-sort a higher one;
      this key makes that impossible structurally, not just by convention). `-score`
      (descending) and then `id_sort_key(id)` only ever run as tie-breakers BETWEEN two
      tickets that already share the same `_priority_rank` — goal matches, relation
      boosts, unblocks and due-date urgency all live inside `score`, so they still change
      ordering, but only among tickets at the same declared level.
    """
    today = today or datetime.date.today()
    buckets = {"future": [], "owner_decisions": [], "blocked": [], "paused": [],
              "quick_wins": [], "do_now": []}
    for t in tickets:
        if t.get("is_archived") or t.get("state") not in CANDIDATE_STATES:
            continue
        e = explain_ticket(t, goal, today)
        is_future = e.pop("_future")
        decision_required = e.pop("_decision_required")
        is_blocked = e.pop("_is_blocked")
        is_paused = e.pop("_paused")
        is_quick_win = e.pop("_quick_win")
        if is_future:
            bucket = "future"
        elif decision_required:
            bucket = "owner_decisions"
        elif is_blocked:
            bucket = "blocked"
        elif is_paused:
            bucket = "paused"
        elif is_quick_win:
            bucket = "quick_wins"
        else:
            bucket = "do_now"
        e["bucket"] = bucket
        buckets[bucket].append(e)
    for items in buckets.values():
        # `_priority_rank(e["priority"])` first and alone — that is the whole T-042 fix.
        # `-e["score"]` and the id only ever break a tie between two entries that already
        # share the same rank; `priority` is part of the public entry shape (read, not
        # popped), so this needs no internal-only key of its own.
        items.sort(key=lambda e: (_priority_rank(e["priority"]), -e["score"], id_sort_key(e["id"])))
    return buckets


BUCKET_ORDER = (("do_now", "Do now"), ("owner_decisions", "Owner decisions"),
                ("blocked", "Blocked"), ("paused", "Paused"), ("quick_wins", "Quick wins"),
                ("future", "Future"))


def explain_line(e):
    """The `--why` line for one recommendation — e.g. 'Level 2, required by parent T-040,
    matches current goal, unblocks T-041.' Every clause is a `reasons` entry
    `explain_ticket` already derived from declared metadata; this only joins them."""
    return ", ".join(e["reasons"]) + "." if e["reasons"] else "(no recorded metadata)"


def render_recommendation(buckets, why=False):
    """The one text rendering of a `classify_and_rank` result — shared by `ai-os tickets
    next` and `ai-os context`'s recommended-next-actions view, so the same underlying
    records never print two differently-shaped recommendations depending on which command
    was asked. Returns a string; never prints, so either caller controls its own output."""
    total = sum(len(v) for v in buckets.values())
    if total == 0:
        return "no ticket recommendations — no live, non-archived ticket in scope"
    lines = []
    for key, label in BUCKET_ORDER:
        items = buckets[key]
        if not items:
            continue
        lines.append(f"{label} ({len(items)})")
        for e in items:
            prio = e["priority"].replace("_", " ").title() if e["priority"] else "no priority"
            lines.append(f"  {e['id']:<10} {prio:<10} score {e['score']:<4} "
                         f"[{e['confidence']} confidence]  {e['title']}")
            if e["blockers"]:
                lines.append(f"  {'':<10} blocked: {e['blockers']}")
            if why:
                lines.append(f"  {'':<10} -> {explain_line(e)}")
        lines.append("")
    return "\n".join(lines).rstrip("\n")


# --- Ticket lifecycle: creation and promotion (T-043) --------------------------------------
# The entry gate for the Smart Dynamic Ticket System: a ticket that cannot recommend
# anything useful about itself (no priority, no goal, no requirement) must not be allowed
# to exist as scheduled work in the first place — `doctor`'s equivalent checks are an
# after-the-fact drift report for tickets that predate this contract; these are the
# before-the-fact refusal used by `ai-os tickets new`/`promote`, in `ai-os-tickets`.
#
# Deliberately the same three fields `CONFIDENCE_FIELDS` already names: the fields whose
# absence lowers a recommendation's confidence are exactly the fields a new, schedulable
# ticket must supply — one definition of "complete intent metadata", not two.
REQUIRED_INTENT_FIELDS = CONFIDENCE_FIELDS

# A `future_candidate` is a deliberately lighter-weight record — a parked idea worth
# tracking as a ticket rather than only as prose in `future.md` — and is exempt from
# `REQUIRED_INTENT_FIELDS` for exactly that reason (see `requirements.md`'s own PARKED/
# EXTENSION split). `ai-os tickets promote` is the one path that moves a ticket OUT of
# this relation, and promoting always re-imposes the full requirement.
INTENT_EXEMPT_RELATION = "future_candidate"


def lifecycle_issues(meta, by_id):
    """Deterministic errors for a ticket's *proposed* metadata, checked BEFORE it is ever
    written or changed — never a warning, never a guess: every one of these is a reason
    `ai-os tickets new`/`promote` refuses outright, so an incomplete or invalid ticket can
    never enter the system in the first place. Reuses the exact enum tables and formats
    `ai-os tickets doctor` already checks (`STATES`, `CLASSES`, `RELATIONS`, `PRIORITIES`,
    `BLOCKED_BY`, `EFFORTS`, `RISKS`, `CONFIDENCES`, `BOOLEANS`, `DATE_RE`) so a value
    refused here would also have been flagged by doctor tomorrow — one rule set, checked
    at two different times, never two rule sets that could drift apart.

    `meta` is a plain dict of the ticket's OWN field names (title/state/class/relation/
    parent/goal/requirement/priority/decision_required/blocked_by/unblocks/effort/risk/
    confidence/due/last_touched) — the same shape `load()` returns, so a caller can pass
    either a brand-new proposal or an existing ticket's current metadata merged with
    proposed changes. `by_id` is every OTHER ticket id already known (across every
    project) — used only to confirm `parent`/`unblocks` reference something real; this
    function performs no filesystem or network access of its own.
    """
    errors = []
    if not (meta.get("title") or "").strip():
        errors.append("title is required")

    state = meta.get("state") or "todo"
    if state not in STATES:
        errors.append(f"state '{state}' is not one of {'/'.join(STATES)}")
    klass = meta.get("class")
    if klass and klass not in CLASSES:
        errors.append(f"class '{klass}' is not one of {'/'.join(CLASSES)}")

    relation = meta.get("relation")
    parent = meta.get("parent")
    if relation and relation not in RELATIONS:
        errors.append(f"relation '{relation}' is not one of {'/'.join(RELATIONS)}")
    if parent and parent not in by_id:
        errors.append(f"parent '{parent}' does not match any existing ticket id")
    if relation in ("required", "optional", "blocks_parent") and not parent:
        errors.append(f"relation '{relation}' requires 'parent'")
    if relation == "parent" and parent:
        errors.append("relation 'parent' must not also declare 'parent'")

    priority = meta.get("priority")
    if priority and priority not in PRIORITIES:
        errors.append(f"priority '{priority}' is not one of {'/'.join(PRIORITIES)}")
    blocked_by = meta.get("blocked_by")
    if blocked_by and blocked_by not in BLOCKED_BY:
        errors.append(f"blocked_by '{blocked_by}' is not one of {'/'.join(BLOCKED_BY)}")
    effort = meta.get("effort")
    if effort and effort not in EFFORTS:
        errors.append(f"effort '{effort}' is not one of {'/'.join(EFFORTS)}")
    risk = meta.get("risk")
    if risk and risk not in RISKS:
        errors.append(f"risk '{risk}' is not one of {'/'.join(RISKS)}")
    confidence = meta.get("confidence")
    if confidence and confidence not in CONFIDENCES:
        errors.append(f"confidence '{confidence}' is not one of {'/'.join(CONFIDENCES)}")
    decision_required = meta.get("decision_required")
    if decision_required and decision_required not in BOOLEANS:
        errors.append(f"decision_required '{decision_required}' is not one of "
                      f"{'/'.join(BOOLEANS)}")
    for field in ("due", "last_touched"):
        value = meta.get(field)
        if value and not DATE_RE.match(value):
            errors.append(f"{field} '{value}' is not in 'YYYY-MM-DD' form")
    for uid in meta.get("unblocks") or []:
        if uid not in by_id:
            errors.append(f"unblocks references '{uid}', which does not match any "
                          f"ticket id")

    if relation != INTENT_EXEMPT_RELATION:
        for field in REQUIRED_INTENT_FIELDS:
            if not meta.get(field):
                errors.append(f"'{field}' is required — a ticket cannot enter the system "
                              f"as schedulable work without it (relation "
                              f"'{INTENT_EXEMPT_RELATION}' is the one exemption)")
    return errors


def next_ticket_id(tickets):
    """The next unused Atlas-native (`T-###`) id, scanning every `T-*` id already
    discovered — any project, any state, archived included — so a fresh id can never
    collide with one already in use anywhere in the workspace. Numbers are never reused
    and never skipped by guesswork: this is `max(existing) + 1`, or `T-001` when no `T-*`
    ticket exists yet. `AIOS-*` ids are a separate, frozen generation (see
    `GENERATION_PATTERNS`'s own comment) and never influence this number."""
    nums = []
    for t in tickets:
        parsed = parse_ticket_id(t.get("id"))
        if parsed and parsed[0] == "T":
            nums.append(parsed[1])
    return f"T-{(max(nums) + 1) if nums else 1:03d}"


# --- Smart Automatic Ticket Archive System (T-044) ----------------------------------------
# The gate a `done`/`cancelled` ticket must clear before ANYTHING archives it automatically
# — the checkpoint-triggered path and the `archive --auto` reconciliation path both call
# this, so "what counts as genuinely finished" is decided once, here, never twice. `archive`
# (plain, `--apply`) is unchanged and keeps its old state-only eligibility — this gate only
# gates the two *automatic* paths T-044 adds, per that ticket's own compatibility contract.
#
# `per_ticket_errors` is the exact per-record rule set `doctor` already enforces (the same
# messages, same order), pulled out once so the gate can reuse it instead of maintaining a
# second copy of "what does a structurally sound ticket look like" that could drift from
# doctor's own answer. `doctor`'s project-level checks (generated index freshness) are
# deliberately NOT part of this — those describe the whole workspace's view of a moment, not
# whether one ticket's own record is sound, and archiving is exactly the operation that makes
# that view stale until the next `index --write`/refresh.
def per_ticket_errors(t, known_ids):
    """Structural errors for one ticket record. `known_ids` is every other ticket id known
    in this discovery — used only to confirm `parent`/`unblocks` resolve to something real.
    Warnings (soft length checks, missing-but-optional metadata, extra undeclared artifact
    files) are `doctor`'s business only; this returns hard errors alone, the set that also
    decides whether a ticket is even ELIGIBLE to be considered sound enough to archive.
    """
    errors = []
    where = t["id"] or t["path"]
    parent = t.get("parent")
    relation = t.get("relation")
    for field in required_fields_for(t["id"]):
        if not t["meta"].get(field):
            errors.append(f"{where}: missing frontmatter '{field}'")
    if t["id"] and t["id"] != t["dir_name"]:
        errors.append(f"{where}: id does not match its directory '{t['dir_name']}'")
    generation = parse_ticket_id(t["id"])
    if generation and generation[0] == "T":
        errors.extend(atlas_metadata_issues(Path(t["path"]).read_text(), t["meta"], t["id"]))
    if t["state"] and t["state"] not in STATES:
        errors.append(f"{where}: state '{t['state']}' is not one of {'/'.join(STATES)}")
    if t["klass"] and t["klass"] not in CLASSES:
        errors.append(f"{where}: class '{t['klass']}' is not one of {'/'.join(CLASSES)}")
    if t["expected_context"] and t["expected_context"] not in SCOPES:
        errors.append(f"{where}: expected_context '{t['expected_context']}' "
                      f"is not one of {'/'.join(SCOPES)}")
    if relation and relation not in RELATIONS:
        errors.append(f"{where}: relation '{relation}' is not one of {'/'.join(RELATIONS)}")
    if parent and parent not in known_ids:
        errors.append(f"{where}: parent '{parent}' does not match any ticket id")
    if relation in ("required", "optional", "blocks_parent") and not parent:
        errors.append(f"{where}: relation '{relation}' requires frontmatter 'parent'")
    if relation == "parent" and parent:
        errors.append(f"{where}: relation 'parent' must not also declare 'parent'")
    priority = t.get("priority")
    if priority and priority not in PRIORITIES:
        errors.append(f"{where}: priority '{priority}' is not one of {'/'.join(PRIORITIES)}")
    blocked_by = t.get("blocked_by")
    if blocked_by and blocked_by not in BLOCKED_BY:
        errors.append(f"{where}: blocked_by '{blocked_by}' is not one of "
                      f"{'/'.join(BLOCKED_BY)}")
    effort = t.get("effort")
    if effort and effort not in EFFORTS:
        errors.append(f"{where}: effort '{effort}' is not one of {'/'.join(EFFORTS)}")
    risk = t.get("risk")
    if risk and risk not in RISKS:
        errors.append(f"{where}: risk '{risk}' is not one of {'/'.join(RISKS)}")
    confidence = t.get("confidence")
    if confidence and confidence not in CONFIDENCES:
        errors.append(f"{where}: confidence '{confidence}' is not one of "
                      f"{'/'.join(CONFIDENCES)}")
    decision_required = t.get("decision_required")
    if decision_required and decision_required not in BOOLEANS:
        errors.append(f"{where}: decision_required '{decision_required}' is not one of "
                      f"{'/'.join(BOOLEANS)}")
    for field in ("due", "last_touched"):
        value = t.get(field)
        if value and not DATE_RE.match(value):
            errors.append(f"{where}: {field} '{value}' is not in 'YYYY-MM-DD' form")
    for uid in t.get("unblocks") or []:
        if uid not in known_ids:
            errors.append(f"{where}: unblocks references '{uid}', which does not "
                          f"match any ticket id")
    present = {p.name for p in Path(t["dir"]).iterdir()
              if p.is_file() and p.name != "task.md"}
    declared = set(t["artifacts"])
    for missing in sorted(declared - present):
        errors.append(f"{where}: artifacts lists '{missing}', which does not exist")
    if t["state"] in LIVE and not t["next_action_line"]:
        errors.append(f"{where}: is {t['state']} but has no Next action")
    return errors


ARCHIVABLE_STATES = ("done", "cancelled")


def archive_completion_gate(t, all_tickets):
    """Reasons a ticket may NOT be automatically archived — empty list means it is
    eligible. Priority is never one of them: a genuinely completed Level 1 ticket is exactly
    as archivable as a genuinely completed Level 5 one (T-044's own contract). Checked, in
    order: already archived; state; recognized id generation; duplicate id authority;
    every structural error `doctor` would also report; an open required/blocks_parent child
    that still names this ticket as its parent.
    """
    reasons = []
    if t.get("is_archived"):
        return [f"{t.get('id')}: already archived"]
    if t.get("state") not in ARCHIVABLE_STATES:
        return [f"{t.get('id')}: state is '{t.get('state')}', not done/cancelled"]
    if parse_ticket_id(t.get("id")) is None:
        return [f"{t.get('id')}: id is not a recognized AIOS-###/T-### generation"]

    known_ids = {x["id"] for x in all_tickets if x.get("id")}
    dup_count = sum(1 for x in all_tickets if x.get("id") == t["id"])
    if dup_count > 1:
        reasons.append(f"{t['id']}: duplicate ticket id — declared by {dup_count} records")

    reasons.extend(per_ticket_errors(t, known_ids))

    for other in all_tickets:
        if other is t or other.get("is_archived"):
            continue
        if (other.get("parent") == t["id"]
                and other.get("relation") in ("required", "blocks_parent")
                and other.get("state") not in ARCHIVABLE_STATES):
            reasons.append(f"{t['id']}: has an open required child {other['id']} "
                          f"(state: {other['state']}) that still depends on it")
    return reasons

