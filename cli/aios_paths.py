"""aios_paths — the private-workspace path resolver, for Python callers.

The rules live in exactly one place, cli/ai-os-paths. This module runs it once per
workspace and caches the answer, so a moved private root resolves identically whether
the caller is a shell script or a Python one. Two implementations of "where is memory?"
is how the two halves of a half-finished migration end up writing to different stores.

    private_path("memory")        -> Path   raises PathConflict when there is no one answer
    private_path_or_die("memory") -> Path   for a module constant: refuse loudly instead
    private_layout("memory")      -> str    new | old | conflict | none

It resolves. It never creates, moves, copies, merges or deletes anything.
Zero non-stdlib dependencies.
"""
import os
import subprocess
import sys
from pathlib import Path

RESOLVER = Path(__file__).resolve().parent / "ai-os-paths"

_cache = None  # (AI_OS_HOME as seen, {var: value})


class PathConflict(RuntimeError):
    """A private root exists in both layouts, as two different directories.

    Never caught to fall back on one of them: choosing would hide the disagreement, and
    only the user knows which store is current.
    """


def _table():
    """Every root in one subprocess. Re-read when AI_OS_HOME changes under us."""
    global _cache
    home = os.environ.get("AI_OS_HOME", "")
    if _cache is not None and _cache[0] == home:
        return _cache[1]
    if not RESOLVER.exists():
        raise RuntimeError(f"broken install: {RESOLVER} is missing")
    out = subprocess.run([str(RESOLVER), "env"], capture_output=True, text=True).stdout
    table = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            table[key] = value
    _cache = (home, table)
    return table


def private_layout(root):
    return _table().get("AI_OS_LAYOUT_" + root.upper(), "unknown")


def private_path(root):
    table = _table()
    path = table.get("AI_OS_PATH_" + root.upper())
    if path is None:
        layout = private_layout(root)
        if layout == "unknown":
            raise KeyError(f"unknown private root {root!r}")
        raise PathConflict(
            f"private root {root!r} has no single answer (layout: {layout}) — "
            f"run: ai-os-paths check"
        )
    return Path(path)


def private_path_or_die(root):
    """The same answer, for a module-level constant in a command.

    A tool that cannot say where its own store is must refuse and name the fix, not
    start up against a guess and not hand the user a traceback.
    """
    try:
        return private_path(root)
    except (PathConflict, KeyError) as exc:
        print(f"\u2717 {exc}", file=sys.stderr)
        raise SystemExit(3)
