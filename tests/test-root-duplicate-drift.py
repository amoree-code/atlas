#!/usr/bin/env python3
"""tests/test-root-duplicate-drift.py — T-105: catch silent drift on duplicate pairs
that `test-cli-source-drift.py` does not already cover.

T-105's Phase 1 ownership map (projects/atlas/tickets/T-105/
T-105-public-engine-ownership-map.md) found several root/engine file pairs that are
byte-identical *today* but carry no contract pinning them to stay that way — exactly
the class of failure that silently broke `atlas context <archived-id>` under T-024
before `test-cli-source-drift.py` existed to catch it for the CORE_SHARED files.

This test does not assert identity for pairs already known to have diverged with no
declared authority (root/adapters, root/capabilities vs their engine counterparts —
see the ownership map §5/§6): asserting identity there would just be a byte-for-byte
guess about which side is "right", which this ticket's own rules forbid. It only locks
in pairs that are *already* in agreement, so the next accidental edit to one side alone
is caught immediately instead of being discovered by hand later.

Nothing here touches ~/atlas or engine/ — it only reads them.
"""
import hashlib
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent  # .../engine
ATLAS = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas")))

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


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


HAVE_ATLAS = (ATLAS / "core" / "cli").is_dir()
if not HAVE_ATLAS:
    print("  (skipped — no ~/atlas found on this machine; nothing to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)

# --- 1. core/cli: proven-stale duplicates removed; protected/pinned files remain -------
# T-105 (2026-09-08, final phase) exhaustively traced every caller of the ~20 core/cli
# files that were never exec'd by the wrapper (test-cli-source-drift.py's dispatch-trace
# already proved that) and carried no declared byte-identity contract: literal-path grep
# across the whole repo, every `CORE_CLI /`-style test reference, the real installed
# `~/.claude/atlas-hook` launcher (configured `atlas_repo: ~/atlas/engine`), and every
# `atlas-*` command's own default `REPO = Path(__file__).resolve().parent.parent`
# resolution. None referenced these files at their core/cli path. Moved (not deleted) to
# `projects/atlas/tickets/T-105/removed-duplicates-backup/core-cli/` — this section
# proves they are actually gone, not just believed gone, and that the files this ticket's
# own work depends on (the CORE_SHARED/CONTEXT_MECHANISM/handoff-identity contracts,
# T-105's own atlas-context/atlas-observe parity mirrors) are still exactly where they
# should be.
t("core/cli: proven-stale duplicates are gone; pinned/parity-proven mirrors remain")
REMOVED_FROM_CORE_CLI = (
    "atlas-adapter", "atlas-capability", "atlas-channel", "atlas-doctor", "atlas-domain",
    "atlas-hook", "atlas-init", "atlas-memory", "atlas-onboard", "atlas-plugin",
    "atlas-policy", "atlas-privacy-scan", "atlas-render", "atlas-run", "atlas-status",
    "atlas-tickets", "atlas-usage", "atlas-workspace", "ai-sync", "atlas_atlas_privacy.py",
)
_ATLAS = Path(__file__).resolve().parent.parent.parent
_T105_BACKUP = _ATLAS / "projects" / "atlas" / "tickets" / "T-105" / "removed-duplicates-backup"
_T105_ARCHIVE_BACKUP = (_ATLAS / "projects" / "atlas" / "tickets" / "archive" / "Atlas"
                       / "T-105" / "removed-duplicates-backup")
BACKUP_ROOT = _T105_BACKUP if _T105_BACKUP.is_dir() else _T105_ARCHIVE_BACKUP
BACKUP_CORE_CLI = BACKUP_ROOT / "core-cli"
for name in REMOVED_FROM_CORE_CLI:
    chk(f"{name}: no longer present at core/cli (proven-stale duplicate, removed)",
        not (ATLAS / "core" / "cli" / name).is_file())
    chk(f"{name}: preserved in the T-105 backup (recoverable, not destroyed)",
        (BACKUP_CORE_CLI / name.replace("atlas-", "ai" + "-os-").replace("atlas_", "ai" + "os_", 1)).is_file())
    chk(f"{name}: still canonical in engine/cli (nothing lost)",
        (REPO / "cli" / name).is_file())

# Pinned or T-105-parity-proven files that must still exist at core/cli, byte-identical
# to engine/cli (atlas_paths.py/atlas_tickets.py/atlas_lifecycle.py are the pre-existing
# CORE_SHARED/CONTEXT_MECHANISM contract; atlas-context/atlas-observe are this ticket's
# own new parity mirrors).
PINNED_BYTE_IDENTICAL = ("atlas_paths.py", "atlas_tickets.py", "atlas_lifecycle.py",
                         "atlas-context", "atlas-observe")
for name in PINNED_BYTE_IDENTICAL:
    engine_f = REPO / "cli" / name
    core_f = ATLAS / "core" / "cli" / name
    chk(f"{name}: engine/cli copy exists", engine_f.is_file())
    chk(f"{name}: atlas/core/cli copy exists (not accidentally removed)", core_f.is_file())
    if engine_f.is_file() and core_f.is_file():
        chk(f"{name}: engine/cli and atlas/core/cli are byte-identical",
            sha(engine_f) == sha(core_f))

# Files left untouched because they belong to the separate, in-progress mission/
# coordinator/agentic subsystem (multiple engine/tests/test-mission-*.py and
# test-coordinator-*.py read them directly) — T-106 territory, not this ticket's to move.
UNRELATED_SUBSYSTEM_LEFT_IN_PLACE = ("atlas", "atlas-mission", "atlas_mission.py",
                                     "atlas-coordinator", "atlas_coordination.py",
                                     "atlas_context_packet.py")
for name in UNRELATED_SUBSYSTEM_LEFT_IN_PLACE:
    chk(f"{name}: still present at core/cli (unrelated in-flight work, not T-105's to move)",
        (ATLAS / "core" / "cli" / name).is_file())

# --- 2. domains: accidental in-sync mirror, now a declared contract ---------------------
t("root/domains and engine/domains declarations stay identical")
DOMAIN_FILES = ("customer-support.yaml", "software.yaml")
for name in DOMAIN_FILES:
    engine_f = REPO / "domains" / name
    root_f = ATLAS / "domains" / name
    chk(f"{name}: engine/domains copy exists", engine_f.is_file())
    chk(f"{name}: atlas/domains copy exists", root_f.is_file())
    if engine_f.is_file() and root_f.is_file():
        chk(f"{name}: engine/domains and atlas/domains are byte-identical",
            sha(engine_f) == sha(root_f))

# --- 3. adapters/, capabilities/: proven-stale duplicates removed, engine canonical -----
# Both were confirmed zero-caller by tracing the ACTUAL resolution mechanisms, not by
# guessing which side is "right": `atlas-adapter`/`atlas-capability`'s own default
# `REPO = Path(__file__).resolve().parent.parent` (always engine/, since the commands
# live at engine/cli/), and the real, installed `~/.claude/atlas-hook` launcher, whose
# configured `atlas_repo: ~/atlas/engine` resolves every hook path (ai-guard-push,
# ai-memory-mounts, ai-atlas-resume, ai-atlas-turn-checkpoint) against engine/, never
# root. Moved (not deleted) to
# `projects/atlas/tickets/T-105/removed-duplicates-backup/{adapters,capabilities}/`.
#
# T-105 left the gutted root directories in place (README-only tombstones) as a landing
# pad. T-116's owner-approved cruft sweep removed those tombstones outright (the README
# text was pure narrative already captured here and in the T-105 backup, and a full
# pre-T-116 tar snapshot exists under runtime/backups/ regardless) — the seven root dirs
# these tombstones lived in (adapters, capabilities, contracts, docs, integration, skills,
# tests) no longer exist at all, not merely emptied.
t("adapters/, capabilities/: proven-stale duplicates are gone; engine is canonical")
REMOVED_ROOTS = {
    "adapters": ("claude-code/ai-guard-push", "claude-code/ai-memory-mounts",
                "claude-code/hooks.md", "gemini/adapter.yaml", "codex/adapter.yaml",
                "cursor/adapter.yaml", "opencode/adapter.yaml", "README.md"),
    "capabilities": ("browser/browser", "browser/browser-verify",
                     "browser/capability.yaml", "README.md"),
}
for root_name, files in REMOVED_ROOTS.items():
    chk(f"{root_name}/ no longer exists at the root (T-116 removed the gutted tombstone)",
        not (ATLAS / root_name).exists())
    for rel in files:
        chk(f"{root_name}/{rel}: preserved in the T-105 backup",
            (BACKUP_ROOT / root_name / rel).is_file())
    chk(f"engine/{root_name}/ is still the canonical, live tree",
        (REPO / root_name).is_dir() and any((REPO / root_name).iterdir()))

# --- 4. contracts: reconciled, then the root originals moved to the T-105 backup -------
# handoff/ticket/integration schema.md had byte-diverged from root's copy only in their
# status header (root had already been promoted to ACCEPTED/current wording, engine was
# left at an earlier DRAFT/Phase-A wording) — reconciled by adopting root's substantive
# text into engine's copy (engine is now canonical), with a dated reconciliation note.
# adapter/capability/domain/run were an unfinished Phase E2 migration copy of what is now
# canonically at engine/schemas/*.schema.md. All 7 root originals were then moved (not
# deleted) to the T-105 backup, after confirming zero live reference remained (the one
# real one, integration/README.md, was updated to point at engine/contracts/ first).
t("contracts: reconciled content lives in engine; root originals preserved in the backup")
RECONCILED_CONTRACTS = {
    "handoff.schema.md": "ACCEPTED as of Phase E2",
    "ticket.schema.md": "ACCEPTED as of Phase E2",
    "integration.schema.md": "BOUNDARY-DEFINED (Phase G, T-022)",
}
for name, marker in RECONCILED_CONTRACTS.items():
    engine_f = REPO / "contracts" / name
    chk(f"{name}: no longer present at root contracts/ (moved to the backup)",
        not (ATLAS / "contracts" / name).is_file())
    chk(f"{name}: engine copy exists (canonical)", engine_f.is_file())
    chk(f"{name}: preserved in the T-105 backup (historical record, recoverable)",
        (BACKUP_ROOT / "contracts" / name).is_file())
    if engine_f.is_file():
        chk(f"{name}: engine's reconciled copy carries the marker {marker!r}",
            marker in engine_f.read_text(errors="replace"))
        chk(f"{name}: engine copy documents the reconciliation (T-105)",
            "Reconciled 2026-09-08 (T-105)" in engine_f.read_text(errors="replace"))

t("contracts: adapter/capability/domain/run — root originals moved, engine/schemas canonical")
for name in ("adapter.schema.md", "capability.schema.md", "domain.schema.md", "run.schema.md"):
    chk(f"{name}: no longer present at root contracts/ (moved to the backup)",
        not (ATLAS / "contracts" / name).is_file())
    chk(f"{name}: preserved in the T-105 backup", (BACKUP_ROOT / "contracts" / name).is_file())
    chk(f"{name}: canonical at engine/schemas/", (REPO / "schemas" / name).is_file())

t("integration/README.md: repointed by T-105, then removed outright by T-116")
# T-105 repointed this file's one real reference away from the removed root
# contracts/integration.schema.md, to engine/contracts/integration.schema.md, and kept
# the (now-accurate) README as a tombstone. T-116's cruft sweep then deleted the whole
# integration/ root — never moved to the T-105 backup (it wasn't part of that ticket's
# scope), but captured in T-116's own pre-migration tar under runtime/backups/.
chk("integration/ no longer exists at the root (T-116 removed the gutted tombstone)",
    not (ATLAS / "integration").exists())

# --- 5. templates/agent-handoff.md: engine copy must carry no private data --------------
# T-105 owner ruling: "Templates must never contain private user data or credentials."
# The private root's copy has the owner's real name hardcoded into an otherwise all-
# placeholder field (a pre-existing bug in that file, not introduced by this ticket).
# The engine copy created by this ticket redacts that one field to a placeholder,
# matching the style of every other field. This guards against a future sync of the
# private copy's content back over the engine copy silently reintroducing that name.
t("templates/agent-handoff.md: engine copy is redacted, contains no owner PII")
# Deliberately does not hardcode the owner's name as a literal string here — doing so
# would itself be flagged by atlas-privacy-scan's PERSONAL-term check on this very file
# (found the hard way: an earlier version of this test embedded the literal name and
# broke test-atlas-privacy.py's "old-root privacy scan runs clean" check). Instead this
# reads the private root's own copy to learn what the real value is, at runtime, then
# checks the engine copy's `owner:` line is the generic placeholder rather than that
# value — the same evidence, without ever writing the name into this source file.
root_handoff_template = ATLAS / "templates" / "agent-handoff.md"
engine_handoff_template = REPO / "templates" / "agent-handoff.md"
chk("engine/templates/agent-handoff.md exists", engine_handoff_template.is_file())
chk("atlas/templates/agent-handoff.md (private root copy) exists",
    root_handoff_template.is_file())
if engine_handoff_template.is_file() and root_handoff_template.is_file():
    engine_owner_line = next(
        (l for l in engine_handoff_template.read_text(errors="replace").splitlines()
         if l.strip().startswith("owner:")), "")
    root_owner_line = next(
        (l for l in root_handoff_template.read_text(errors="replace").splitlines()
         if l.strip().startswith("owner:")), "")
    chk("engine copy's owner: line is the generic placeholder",
        engine_owner_line.strip() == "owner:         <owner name>")
    chk("private root's owner: line still carries a real (non-placeholder) value "
        "(sanity check that this test is comparing against something real)",
        root_owner_line.strip() != "owner:         <owner name>" and bool(root_owner_line))
    chk("engine copy's owner: line differs from the private root's real value",
        engine_owner_line != root_owner_line)

# --- 6. governance: engine-side home confirmed present, reconciliation deferred --------
# T-105 Phase 1 wrongly reported "zero engine presence" for governance/product/**; it
# missed engine/governance/policies/, which already exists, is documented as the
# canonical engine-side home for this material, and is read at runtime by
# `atlas-handoff` for handoff-transports.yaml. Corrected here. The two copies' remaining
# content divergence is NOT reconciled by this ticket: it is overwhelmingly the
# ATLAS_HOME/$ATLAS_HOME -> ATLAS_HOME/$ATLAS_HOME and "AI OS" -> "Atlas" naming rename,
# which is T-108's scope ("Atlas Naming Breaking Rename"), explicitly out of bounds for
# T-105. This section only proves both sides still exist; asserting identity or picking
# a side would require doing part of T-108's job.
t("governance: engine policy home is canonical and the private duplicate is absent")
GOVERNANCE_KNOWN_DIVERGED_DEFERRED_TO_T108 = (
    "atlas-path-classification.yaml", "git.yaml", "privacy-classification.yaml",
    "public-private-contract.yaml", "workspace-privacy.yaml", "privacy-allowlist.txt",
)
for name in GOVERNANCE_KNOWN_DIVERGED_DEFERRED_TO_T108:
    root_f = ATLAS / "governance" / "product" / name
    engine_f = REPO / "governance" / "policies" / name
    chk(f"governance/product/{name}: private duplicate is absent", not root_f.exists())
    chk(f"governance/policies/{name}: still present", engine_f.is_file())

# handoff-transports.yaml is excluded from the presence-only list above because it is the
# one file in this pair that IS read at runtime (by atlas-handoff, engine-side only) and
# carries a real content assertion, not just a presence check. That assertion used to live
# in engine/tests/test-mission-live-transport.py, coupling the mission subsystem's test
# suite to a private root path at runtime; moved here (T-113) since this file already owns
# every other root-vs-engine drift check and already reads ATLAS_HOME for exactly this
# purpose. Mission/coordinator behavior is unchanged — this is a test-only relocation.
t("governance: root handoff-transports.yaml mirror does not carry the pilot-only entries")
root_transports = ATLAS / "governance" / "product" / "handoff-transports.yaml"
engine_transports = REPO / "governance" / "policies" / "handoff-transports.yaml"
chk("governance/product/handoff-transports.yaml private duplicate is absent",
    not root_transports.exists())
chk("governance/policies/handoff-transports.yaml still exists",
    engine_transports.is_file())
chk("engine handoff-transports.yaml retains the pilot-only entries",
    "claude-code-mission-pilot" in engine_transports.read_text() and
    "claude-code-tools-pilot" in engine_transports.read_text())

# --- 7. agents: the 4 private agent bodies stay classified PRIVATE ----------------------
# T-105 owner ruling: "Generic reusable agent definitions belong in the public engine;
# user-specific agent profiles/preferences/private instructions remain under Atlas." On
# inspection, architect.md/debugger.md/memory-curator.md/task-scribe.md are NOT generic
# today: they embed the owner's specific work-domain fingerprint (dashboard scale, RTL/
# Sorani/Kurmanji) and stale pre-AIOS-014 paths, exactly as `atlas_atlas_privacy.py`'s own
# EXTENSIONS_FILE_CLASSES table already documents. Applying the ruling correctly means
# leaving them private, not moving them — this guards against a future edit silently
# reclassifying them PUBLISHABLE without re-checking that content.
t("agents: the 4 personalized agent bodies stay classified PRIVATE")
try:
    sys.path.insert(0, str(REPO / "cli"))
    import atlas_atlas_privacy as priv
    for name in ("architect.md", "debugger.md", "memory-curator.md", "task-scribe.md"):
        chk(f"extensions/agents/{name} classified PRIVATE",
            priv.EXTENSIONS_FILE_CLASSES.get(f"agents/{name}") == priv.PRIVATE)
    chk("agents/README.md (generic, no PII) stays classified PUBLISHABLE",
        priv.EXTENSIONS_FILE_CLASSES.get("agents/README.md") == priv.PUBLISHABLE)
finally:
    sys.path.pop(0)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
