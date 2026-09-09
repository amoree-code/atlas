#!/usr/bin/env python3
"""T-124: prior-work matching covers declared intent and archived records."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

CLI = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_loader(
    "atlas_tickets_prior_work", SourceFileLoader("atlas_tickets_prior_work",
                                                  str(CLI / "cli" / "atlas_tickets.py")))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


old = {"id": "T-001", "title": "Old setup", "objective": "Configure provider adapters",
       "scope": "provider discovery", "references": [], "is_archived": True, "state": "done"}
new = mod.prior_work_candidates(
    "Prepare onboarding", "Configure provider adapters", "provider discovery", [], [old])
assert len(new) == 1
assert new[0][0]["id"] == "T-001"
assert set(new[0][2]) == {"objective", "scope"}
assert new[0][1] > mod.DUPLICATE_HIGH_CONFIDENCE
print("PASS prior-work matching uses objective/scope and includes archived records")
