"""aios_atlas_privacy — path-based publication-eligibility classification for $ATLAS_HOME.

Answers "is this path even eligible for publication" BEFORE any content scan runs. See
internal/governance/policies/atlas-path-classification.yaml for the full rationale; this
module is the enforced version of that policy's `roots` table, the same relationship
aios_tickets.py's STATES/CLASSES have to internal/schemas/task.md.

The two-root boundary (workspace-privacy.yaml) `ai-os-privacy-scan` enforces today assumes
the physical root already tells you which side of the line a file is on. That assumption
does not hold once $ATLAS_HOME exists — one tree, private and publishable material both
inside it. This module is the new, additive boundary; it does not replace or weaken the old
one, which stays fully in force for as long as ~/.ai-os and the public repo both hold real
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


def classify_root(root_name):
    """The ROOTS entry for a top-level Atlas root name, or None if unrecognized."""
    return ROOTS.get(root_name)


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
        return cls, False, (f"mixed root — private by default until this exact path is "
                            f"explicitly classified/promoted ({info['evidence']})")
    return cls, False, info["evidence"]
