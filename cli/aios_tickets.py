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


def load(path):
    text = path.read_text()
    meta, body = parse_frontmatter(text)
    na = section(body, "Next action") or ""
    log = section(body, "Log") or ""
    return {
        "path": str(path),
        "dir": str(path.parent),
        "dir_name": path.parent.name,
        "project_dir": path.parent.parent.parent.name,
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
    out = []
    for task in sorted(projects_root.glob("*/tickets/*/task.md")):
        if project and task.parent.parent.parent.name != project:
            continue
        out.append(load(task))
    return out


