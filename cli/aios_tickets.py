"""aios_tickets — reading the durable ticket records, for Python callers.

One implementation of "what does this ticket say", used by `ai-os tickets` and by
`ai-os context`. Two readers of the same records is how two views of one status start
disagreeing, which is the failure this whole area exists to remove.

It reads. It never writes, moves or deletes a record.
Zero non-stdlib dependencies.
"""
import re
from pathlib import Path

STATES = ("todo", "active", "paused", "blocked", "done", "cancelled")
LIVE = ("active", "blocked")
REQUIRED = ("id", "title", "state", "project", "opened", "updated")
CLASSES = ("small", "medium", "large")
SCOPES = ("small", "medium", "large")
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


