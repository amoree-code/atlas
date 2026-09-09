#!/usr/bin/env python3
"""tests/test-context-parity.py — retired by T-116/T-118.

T-105 built this file to prove, by execution, that context/{atlas-context,observe,usage,
lifecycle} and core/cli's copies of the same names behaved identically to engine/cli's —
a prerequisite the owner set before any caller could be cut over to the canonical engine
copy ("cut over callers only after proving parity", 2026-09-08). It did its job: both
gaps it originally found (atlas-context's two-way feature fork, atlas-observe's silent
fallback divergence) were fixed, and every rerun after that proved 3-way parity held.

T-118 acted on that proof: ~/atlas/context/ and the atlas_paths.py/atlas_tickets.py/
atlas_lifecycle.py/atlas-context/atlas-observe mirror files under ~/atlas/core/cli/ were
retired outright (git history has the full original test — every section below the
docstring, and the parity narrative it recorded — for anyone auditing that decision).
engine/cli/ is now the sole implementation of all four commands; the `atlas` dispatcher
routes to it directly, the same way it already routes everything else.

core/cli/ itself has since been retired in full: the mission/coordinator "core vs engine"
parity subsystem it used to also host (T-050/T-051 and family; see
test-coordinator-routing.py, test-mission-*.py) no longer has a second copy to compare
against either. Nothing here touches that.

Nothing left to check: there is exactly one copy of each of these four commands now.
"""
print("  (retired by T-118 — context/core dispatch mirrors no longer exist; see this "
      "file's own docstring)")
print("\n0 passed, 0 failed")
