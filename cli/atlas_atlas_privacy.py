"""atlas_atlas_privacy — path-based publication-eligibility classification for $ATLAS_HOME.

Answers "is this path even eligible for publication" BEFORE any content scan runs. See
internal/governance/policies/atlas-path-classification.yaml for the full rationale; this
module is the enforced version of that policy's `roots` table, the same relationship
atlas_tickets.py's STATES/CLASSES have to internal/schemas/task.md.

The two-root boundary (workspace-privacy.yaml) `atlas-privacy-scan` enforces today assumes
the physical root already tells you which side of the line a file is on. That assumption
does not hold once $ATLAS_HOME exists — one tree, private and publishable material both
inside it. This module is the new, additive boundary; it does not replace or weaken the old
one, which stays fully in force for as long as ~/atlas and the public repo both hold real
content (see the policy file's `relationship` section).

Classification only. Never scans content, never publishes, never edits.
Zero non-stdlib dependencies.
"""
from pathlib import Path

PRIVATE = "private"          # never publishable, full stop
LOCAL = "local"               # machine/runtime state, not source material for publication
PUBLISHABLE = "publishable"   # eligible to ENTER the publication pipeline — never auto-published
MIXED = "mixed"               # both kinds of material; private by default, per-item only

CLASSES = (PRIVATE, LOCAL, PUBLISHABLE, MIXED)

# One entry per frozen top-level root (AIOS-020/candidate-tree.md). `evidence` names the
# candidate-tree.md verdict this is grounded in, so a reviewer never has to trust this
# table blindly — see atlas-path-classification.yaml for the full text and the `note`
# fields on the two roots where a first-pass reading would have been softer than the
# actual evidence.
ROOTS = {
    "core":         {"class": PUBLISHABLE, "evidence": "candidate-tree.md core/: Publishable"},
    "context":      {"class": PUBLISHABLE, "evidence": "candidate-tree.md context/: Publishable, nothing private lives here itself"},
    "personal":     {"class": PRIVATE,     "evidence": "candidate-tree.md personal/: Private, never publishable, non-negotiable"},
    "projects":     {"class": PRIVATE,     "evidence": "candidate-tree.md projects/: Project-name-level PII, never publishable"},
    "adapters":     {"class": MIXED,       "evidence": "candidate-tree.md adapters/: Publishable, except client-specific private config"},
    "capabilities": {"class": PUBLISHABLE, "evidence": "candidate-tree.md capabilities/: Publishable at the contract level"},
    "domains":      {"class": PUBLISHABLE, "evidence": "candidate-tree.md domains/: Publishable"},
    "extensions":   {"class": MIXED,       "evidence": "candidate-tree.md extensions/: publishable skill/agent bodies, private MCP connection detail per-entry"},
    "governance":   {"class": MIXED,       "evidence": "candidate-tree.md governance/: publishable rules/policies, private authority.yaml/workspace policy text"},
    "contracts":    {"class": PUBLISHABLE, "evidence": "candidate-tree.md contracts/: Publishable, contracts are not PII"},
    "runtime":      {"class": LOCAL,       "evidence": "candidate-tree.md runtime/: Generated/transient, never publishable as data"},
    "integration":  {"class": MIXED,       "evidence": "candidate-tree.md integration/: private task content in flight or once reconciled, never itself publishable"},
    "docs":         {"class": PUBLISHABLE, "evidence": "candidate-tree.md docs/: Publishable"},
    "tests":        {"class": PUBLISHABLE, "evidence": "candidate-tree.md tests/: Publishable (suite)"},
}

# Deterministic, default-deny: a root is eligible for the publication pipeline only if
# listed here. Mixed roots are never listed at the root level — per-item promotion is a
# future mechanism, not built by this module.
PUBLICATION_ALLOWLIST = tuple(sorted(
    root for root, info in ROOTS.items() if info["class"] == PUBLISHABLE
))

# --- per-file promotion inside the `governance` mixed root (T-028) --------------------
# The `mixed` class above is private-by-default at the root level; ROOTS itself names a
# "future mechanism, not built by this module" for promoting individual paths. This table
# is that mechanism, scoped to `governance/` only — the root T-028 was asked to classify.
# It does not extend to any other mixed root (`adapters`, `extensions`, `integration`):
# those stay exactly as default-deny as before this change; do not add entries for them
# speculatively. Every governance file is listed explicitly — private entries are kept
# in the table (rather than just omitted) so the matrix stays visibly complete and a
# reviewer never has to trust an omission. Paths are relative to `governance/` itself.
GOVERNANCE_FILE_CLASSES = {
    "README.md":                                  PRIVATE,
    "authority.yaml":                              PRIVATE,
    "rules/core.md":                               PRIVATE,
    "policies/README.md":                          PRIVATE,
    "policies/context.md":                         PRIVATE,
    "policies/git.md":                             PRIVATE,
    "policies/graph.md":                           PRIVATE,
    "policies/knowledge.md":                       PRIVATE,
    "policies/lifecycle.md":                       PRIVATE,
    "policies/memory.md":                          PRIVATE,
    "policies/models.md":                          PRIVATE,
    "policies/privacy-terms.txt":                  PRIVATE,
    "policies/response.md":                        PRIVATE,
    "policies/stack.md":                           PRIVATE,
    "policies/task.md":                            PRIVATE,
    "policies/verification.md":                    PRIVATE,
    "product/README.md":                           PUBLISHABLE,
    "product/atlas-path-classification.yaml":      PUBLISHABLE,
    "product/git.yaml":                            PUBLISHABLE,
    "product/handoff-transports.yaml":             PUBLISHABLE,
    "product/privacy-allowlist.txt":               PUBLISHABLE,
    "product/privacy-classification.yaml":         PUBLISHABLE,
    "product/public-private-contract.yaml":        PUBLISHABLE,
    "product/workspace-privacy.yaml":               PUBLISHABLE,
}

# --- per-file promotion inside the `extensions` mixed root (T-029) --------------------
# Same mechanism as GOVERNANCE_FILE_CLASSES above, scoped to `extensions/` only — the
# Phase D3 merge (public skills/ + private internal/extensions/{agents,capabilities,mcp,
# skills}) T-029 was asked to execute. Does not extend to `adapters`/`governance`(already
# has its own table)/`integration`: those stay exactly as default-deny as before. Every
# merged file is listed explicitly, private entries included, for the same reviewer-
# visibility reason as the governance table. Paths are relative to `extensions/` itself.
#
# `skills/` (public-origin, canonical, already lived in the public repo) is publishable
# per-directory; `skills/README.md` (the private custom-skill doorway note, migrated from
# internal/extensions/skills/) stays private. `agents/README.md` is generic mechanism
# documentation with no PII and no stale/workspace-specific paths — publishable. The four
# agent bodies (architect/debugger/memory-curator/task-scribe) embed the owner's specific
# work-domain fingerprint (dashboard scale, RTL/Sorani/Kurmanji specifics) and/or stale
# pre-AIOS-014 paths (`~/atlas/user/...`) that no longer exist — private, not yet even
# accurate, let alone client-agnostic. `capabilities/README.md` and `mcp/README.md` both
# reference specific internal ticket/decision paths (AIOS-001 checkpoint, the no-custom-
# mcp-servers decision) — internal narrative, not client-agnostic product text — private.
EXTENSIONS_FILE_CLASSES = {
    "skills/README.md":                PRIVATE,
    "skills/catch-up/SKILL.md":                    PUBLISHABLE,
    "skills/day-start/SKILL.md":                   PUBLISHABLE,
    "skills/project-init/SKILL.md":                PUBLISHABLE,
    "skills/project-register/SKILL.md":            PUBLISHABLE,
    "skills/research/SKILL.md":                    PUBLISHABLE,
    "skills/session-end/SKILL.md":                 PUBLISHABLE,
    "skills/session-handoff/SKILL.md":             PUBLISHABLE,
    "skills/workspace-health/SKILL.md":            PUBLISHABLE,
    "agents/README.md":                PUBLISHABLE,
    "agents/architect.md":              PRIVATE,
    "agents/debugger.md":               PRIVATE,
    "agents/memory-curator.md":         PRIVATE,
    "agents/task-scribe.md":            PRIVATE,
    "capabilities/README.md":           PRIVATE,
    "mcp/README.md":                    PRIVATE,
    # Reserved namespace placeholders — no content yet, but the directories they hold
    # (future MCP server configs/registrations) are exactly where private connection
    # detail would land per ownership-map.md; keep the whole reserved namespace private
    # by default rather than letting an empty-today placeholder read as "harmless."
    "mcp/config/.gitkeep":              PRIVATE,
    "mcp/registry/.gitkeep":            PRIVATE,
    "mcp/servers/.gitkeep":             PRIVATE,
}


def classify_root(root_name):
    """The ROOTS entry for a top-level Atlas root name, or None if unrecognized."""
    return ROOTS.get(root_name)


def _governance_promotion(path, atlas_home):
    """The explicit per-file class for a path under governance/, or None if not listed.

    None covers both "not under governance/" and "under governance/ but not in the
    table" — both fail safe to the caller's existing mixed-root default deny.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(atlas_home).resolve() / "governance")
    except ValueError:
        return None
    return GOVERNANCE_FILE_CLASSES.get(str(rel))


def _extensions_promotion(path, atlas_home):
    """The explicit per-file class for a path under extensions/, or None if not listed.

    Same fail-safe shape as `_governance_promotion` — see EXTENSIONS_FILE_CLASSES (T-029).
    """
    try:
        rel = Path(path).resolve().relative_to(Path(atlas_home).resolve() / "extensions")
    except ValueError:
        return None
    return EXTENSIONS_FILE_CLASSES.get(str(rel))


def atlas_relative_root(path, atlas_home):
    """The top-level root name `path` falls under, relative to `atlas_home`, or None.

    None covers both "not under atlas_home at all" and "directly inside atlas_home with no
    root segment" (e.g. $ATLAS_HOME/README.md) — both fail safe as unrecognized. Resolves
    the path lexically only; the target need not exist on disk, and nothing here inspects
    git state — classification is independent of tracking or staging by construction.
    """
    try:
        rel = Path(path).resolve().relative_to(Path(atlas_home).resolve())
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def publication_eligibility(path, atlas_home):
    """(class, eligible, reason) for a candidate path under $ATLAS_HOME.

    `eligible` answers exactly one question — may this path even be CONSIDERED for
    publication, before any content scan or owner approval runs. It is never the final
    word: a `publishable` root's content can still fail the content scan, and every
    publication still needs explicit owner approval regardless of this answer.

    Default is deny: a path outside $ATLAS_HOME, a root not in ROOTS, a `mixed` root, a
    `private` root and a `local` root are all not eligible. Only `publishable` is.
    """
    root = atlas_relative_root(path, atlas_home)
    if root is None:
        return None, False, "not under $ATLAS_HOME, or no root segment — default deny"
    info = classify_root(root)
    if info is None:
        return None, False, f"'{root}' is not one of the fourteen frozen roots — default deny"
    cls = info["class"]
    if cls == PUBLISHABLE:
        return cls, True, info["evidence"]
    if cls == MIXED:
        if root == "governance":
            promoted = _governance_promotion(path, atlas_home)
            if promoted == PUBLISHABLE:
                return PUBLISHABLE, True, "governance per-file promotion (T-028)"
            if promoted is not None:
                return promoted, False, f"governance per-file classification: {promoted} (T-028)"
        if root == "extensions":
            promoted = _extensions_promotion(path, atlas_home)
            if promoted == PUBLISHABLE:
                return PUBLISHABLE, True, "extensions per-file promotion (T-029)"
            if promoted is not None:
                return promoted, False, f"extensions per-file classification: {promoted} (T-029)"
        return cls, False, (f"mixed root — private by default until this exact path is "
                            f"explicitly classified/promoted ({info['evidence']})")
    return cls, False, info["evidence"]
