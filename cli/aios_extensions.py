"""aios_extensions — isolated discovery/resolution over $ATLAS_HOME/extensions/ (T-029).

Phase D3 (AIOS-020/migration-plan.md) merged the public `skills/` and the private
`internal/extensions/{agents,capabilities,mcp,skills}/` into one `$ATLAS_HOME/extensions/`
tree. This module is the discovery/resolution mechanism for that merged tree, built and
tested in isolation per `migration-prerequisites.md` §3 ("ai-sync path assumptions checked
in isolation first"). It is deliberately NOT wired into `ai-sync` or `ai-os-render`'s live
behavior yet — both keep reading their pre-existing legacy sources
(`<repo>/skills/` for `ai-os-render`) until an explicit, separately-approved cutover step.
See `extensions/README.md` under $ATLAS_HOME and T-029 for the full record.

Discovery only. Never renders, never writes, never publishes.
Zero non-stdlib dependencies.
"""
import os
from pathlib import Path


class ExtensionNameCollision(RuntimeError):
    """Two extension sources register the same name.

    Never resolved by silently picking one — the caller must see the collision. Merging
    is a curation decision, not something this module is allowed to guess at.
    """


def atlas_home():
    return Path(os.environ["ATLAS_HOME"]) if os.environ.get("ATLAS_HOME") \
        else Path.home() / "atlas"


def _extensions_root(atlas_home_path):
    root = Path(atlas_home_path) / "extensions"
    if not root.is_dir():
        # No legacy fallback: a missing Atlas extensions/ tree is an error, never a
        # silent read of <repo>/skills or ~/.ai-os/internal/extensions instead.
        raise FileNotFoundError(
            f"{root} does not exist — extension discovery only reads $ATLAS_HOME/"
            f"extensions/; it never falls back to a legacy source")
    return root


def discover_skills(atlas_home_path=None):
    """{name: Path to SKILL.md} for every skill under extensions/skills/.

    A skill is any immediate subdirectory of extensions/skills/ containing a SKILL.md.
    `extensions/skills/README.md` (the private custom-skill doorway note) is a file, not a
    subdirectory, so it is never mistaken for a skill.
    """
    root = _extensions_root(atlas_home_path or atlas_home()) / "skills"
    if not root.is_dir():
        return {}
    found = {}
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_file = entry / "SKILL.md"
        if skill_file.is_file():
            found[entry.name] = skill_file
    return found


def discover_agents(atlas_home_path=None):
    """{name: Path} for every agent body under extensions/agents/, excluding README.md."""
    root = _extensions_root(atlas_home_path or atlas_home()) / "agents"
    if not root.is_dir():
        return {}
    return {
        p.stem: p for p in sorted(root.glob("*.md"))
        if p.name != "README.md"
    }


def discover_mcp_servers(atlas_home_path=None):
    """[name, ...] for every Atlas-managed MCP server registered under extensions/mcp/servers/.

    Empty today by design (`../extensions/mcp/README.md`'s "ZERO Atlas-managed servers"
    decision) — this walks the real directory rather than hardcoding that fact, so it
    reflects reality the moment a server is ever actually registered.
    """
    root = _extensions_root(atlas_home_path or atlas_home()) / "mcp" / "servers"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def merge_registry(*sources):
    """Merge any number of {name: Path} maps into one, raising on a name collision.

    `sources` are pre-discovered maps (e.g. two calls to `discover_skills` against
    different roots) — this function does no discovery itself, only the merge-with-
    collision-detection step, so duplicate-name handling is testable independent of
    where the names came from.
    """
    merged = {}
    for source in sources:
        for name, path in source.items():
            if name in merged and merged[name] != path:
                raise ExtensionNameCollision(
                    f"'{name}' is registered at both {merged[name]} and {path} — "
                    f"a duplicate name across extension sources is never resolved "
                    f"automatically")
            merged[name] = path
    return merged


def render_source_for(kind, atlas_home_path=None):
    """The single resolved source directory for one extension kind ('skills'/'agents'/'mcp').

    This is the isolated equivalent of what `ai-os-render`'s `SKILLS` constant, or an
    equivalent future `AGENTS`/`MCP` constant, would resolve to if pointed at Atlas. It is
    exercised by tests to prove the resolution logic is correct; `ai-os-render` itself is
    not changed by this module (see module docstring).
    """
    if kind not in ("skills", "agents", "mcp"):
        raise ValueError(f"unknown extension kind: {kind!r}")
    return _extensions_root(atlas_home_path or atlas_home()) / kind
