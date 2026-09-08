#!/usr/bin/env python3
"""tests/test-atlas-extensions.py — T-029: extension discovery/resolution over $ATLAS_HOME.

Proves the isolated discovery mechanism (cli/atlas_extensions.py) built for the Phase D3
extensions/ merge: skill/agent/MCP discovery, duplicate-name behavior, renderer path
resolution, and — the one this ticket cares most about — that a missing $ATLAS_HOME/
extensions/ tree is a loud error, never a silent fallback to a legacy source. Nothing here
touches the real ~/atlas or the public repo's actual skills/ as a live dependency; a
throwaway fixture tree stands in for $ATLAS_HOME throughout.
"""
import importlib.util, sys, tempfile
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
    "atlas_extensions_under_test",
    SourceFileLoader("atlas_extensions_under_test", str(CLI / "atlas_extensions.py")))
ext = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ext)


def make_fixture_tree(root):
    """A minimal extensions/ tree: 2 skills, 2 agents, 1 registered MCP server."""
    skills = root / "extensions" / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / "alpha" / "SKILL.md").write_text("alpha body")
    (skills / "beta").mkdir(parents=True)
    (skills / "beta" / "SKILL.md").write_text("beta body")
    (skills / "README.md").write_text("doorway note")
    agents = root / "extensions" / "agents"
    agents.mkdir(parents=True)
    (agents / "README.md").write_text("agent mechanism doc")
    (agents / "worker.md").write_text("worker body")
    mcp_servers = root / "extensions" / "mcp" / "servers"
    (mcp_servers / "notion").mkdir(parents=True)
    (mcp_servers / "notion" / "server.yaml").write_text("kind: notion")


# =========================================================================================
t("extension discovery: skills")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    make_fixture_tree(atlas)
    found = ext.discover_skills(atlas)
    chk("finds exactly the 2 real skill directories", set(found) == {"alpha", "beta"})
    chk("each maps to its SKILL.md", all(p.name == "SKILL.md" for p in found.values()))
    chk("skills/README.md is never mistaken for a skill", "README.md" not in found)
    chk("skills/README (no .md) is never mistaken for a skill", "README" not in found)

# =========================================================================================
t("extension discovery: agents")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    make_fixture_tree(atlas)
    found = ext.discover_agents(atlas)
    chk("finds exactly the 1 real agent body", set(found) == {"worker"})
    chk("agents/README.md is excluded (mechanism doc, not an agent body)",
        "README" not in found)

# =========================================================================================
t("extension discovery: MCP servers")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    make_fixture_tree(atlas)
    found = ext.discover_mcp_servers(atlas)
    chk("finds the 1 registered server", found == ["notion"])
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    (atlas / "extensions" / "mcp" / "servers").mkdir(parents=True)
    chk("zero registered servers is empty, not an error (matches the real Atlas-managed-"
        "servers-are-zero decision)", ext.discover_mcp_servers(atlas) == [])

# =========================================================================================
t("no accidental legacy fallback: a missing $ATLAS_HOME/extensions/ tree is a loud error")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)  # no extensions/ created at all
    try:
        ext.discover_skills(atlas)
        chk("discover_skills raises rather than silently returning legacy content", False)
    except FileNotFoundError as e:
        chk("discover_skills raises FileNotFoundError, names $ATLAS_HOME/extensions",
            "extensions" in str(e))
    try:
        ext.render_source_for("skills", atlas)
        chk("render_source_for raises rather than resolving to any legacy path", False)
    except FileNotFoundError:
        chk("render_source_for raises FileNotFoundError for a missing Atlas tree", True)

# =========================================================================================
t("duplicate-name behavior: merge_registry never silently picks a winner")
with tempfile.TemporaryDirectory() as tmp:
    atlas1 = Path(tmp) / "one"
    atlas2 = Path(tmp) / "two"
    make_fixture_tree(atlas1)
    make_fixture_tree(atlas2)
    a = ext.discover_skills(atlas1)
    b = ext.discover_skills(atlas2)
    try:
        ext.merge_registry(a, b)
        chk("merging two sources with the same skill name raises", False)
    except ext.ExtensionNameCollision as e:
        chk("raises ExtensionNameCollision naming the duplicate", "alpha" in str(e) or "beta" in str(e))
chk("merging non-overlapping sources succeeds cleanly",
    ext.merge_registry({"x": Path("/a")}, {"y": Path("/b")}) == {"x": Path("/a"), "y": Path("/b")})
chk("merging identical entries (same name, same path) is not treated as a collision",
    ext.merge_registry({"x": Path("/a")}, {"x": Path("/a")}) == {"x": Path("/a")})

# =========================================================================================
t("renderer path resolution: render_source_for resolves the correct Atlas subdirectory")
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp)
    make_fixture_tree(atlas)
    chk("skills resolves to extensions/skills",
        ext.render_source_for("skills", atlas) == atlas / "extensions" / "skills")
    chk("agents resolves to extensions/agents",
        ext.render_source_for("agents", atlas) == atlas / "extensions" / "agents")
    chk("mcp resolves to extensions/mcp",
        ext.render_source_for("mcp", atlas) == atlas / "extensions" / "mcp")
    try:
        ext.render_source_for("not-a-real-kind", atlas)
        chk("an unknown kind raises ValueError", False)
    except ValueError:
        chk("an unknown kind raises ValueError", True)

# =========================================================================================
t("ATLAS_HOME resolution matches the established convention (env override, else ~/atlas)")
import os
old = os.environ.get("ATLAS_HOME")
try:
    os.environ.pop("ATLAS_HOME", None)
    chk("no override -> defaults to ~/atlas", ext.atlas_home() == Path.home() / "atlas")
    os.environ["ATLAS_HOME"] = "/tmp/custom-atlas-for-test"
    chk("ATLAS_HOME override is honored", ext.atlas_home() == Path("/tmp/custom-atlas-for-test"))
finally:
    if old is None:
        os.environ.pop("ATLAS_HOME", None)
    else:
        os.environ["ATLAS_HOME"] = old

# =========================================================================================
t("live check: the real ~/atlas/extensions/ tree (if present) discovers cleanly")
real_atlas = Path.home() / "atlas"
if (real_atlas / "extensions").is_dir():
    real_skills = ext.discover_skills(real_atlas)
    real_agents = ext.discover_agents(real_atlas)
    real_mcp = ext.discover_mcp_servers(real_atlas)
    chk("real extensions/skills/ discovers at least the known 9 canonical skills",
        len(real_skills) >= 9)
    chk("real extensions/agents/ discovers the 4 known agent bodies",
        set(real_agents) == {"architect", "debugger", "memory-curator", "task-scribe"})
    chk("real extensions/mcp/servers/ is empty (zero Atlas-managed servers, as documented)",
        real_mcp == [])
    chk("merging real skills with itself is a no-op, not a collision (identical paths)",
        ext.merge_registry(real_skills, real_skills) == real_skills)
else:
    chk("~/atlas/extensions/ not present on this machine — skipped (not a failure)", True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
