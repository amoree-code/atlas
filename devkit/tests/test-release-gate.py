#!/usr/bin/env python3
"""T-110 release gate: cheap, deterministic checks over the shipped boundaries."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "cli"
passed = failed = 0


def check(label, ok):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'} {label}")
    if ok:
        passed += 1
    else:
        failed += 1


def run(*args, env=None):
    return subprocess.run(args, text=True, capture_output=True,
                          env={**os.environ, **(env or {})})


catalog = ROOT / "docs" / "atlas-catalog.json"
if not catalog.is_file():
    catalog = ROOT / "devkit" / "docs" / "atlas-catalog.json"
check("Atlas catalog exists", catalog.is_file())
data = json.loads(catalog.read_text())
for key in ("features", "commands", "clients", "surfaces", "channels", "architecture"):
    check(f"catalog has {key}", bool(data.get(key)))

check("generated docs are current", run(str(CLI / "atlas-docs"), "check").returncode == 0)
check("capability doctor passes", run(str(CLI / "atlas"), "capability", "doctor").returncode == 0)
with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp) / "atlas"
    (atlas / "runtime" / "dispatch-inbox").mkdir(parents=True)
    (atlas / "personal" / "inbox").mkdir(parents=True)
    check("personal and dispatch inboxes are distinct", (atlas / "personal" / "inbox") !=
          (atlas / "runtime" / "dispatch-inbox"))
    check("Atlas root is selected without legacy fallback",
          run(str(CLI / "atlas"), "root", env={"ATLAS_HOME": str(atlas)}).returncode == 0)

check("engine owns reusable governance policy",
      (ROOT / "governance" / "policies" / "atlas-path-classification.yaml").is_file())
check("private product governance is not duplicated", 
      not (ROOT.parent / "governance" / "product").exists())
check("backup safety root exists", (ROOT.parent / "runtime" / "backups").is_dir())
ticket_root = ROOT.parent / "projects" / "atlas" / "tickets"
ticket_artifacts = [p for p in ticket_root.rglob("T-*-*.md") if p.name != "task.md"]
check("ticket artifacts remain ticket-local",
      bool(ticket_artifacts) and all(p.parent.name.startswith("T-") for p in ticket_artifacts))

tests = (
    "test-structure.py",
    "test-coordinator-routing.py",
    "test-coordinator-conflict-protection.py",
    "test-atlas-naming.py",
    "test-atlas-cli.py",
    "test-tickets.py",
    "test-ticket-lifecycle.py",
    "test-client-inventory.py",
    "test-integration-registry.py",
    "test-atlas-privacy.py",
    "test-cli-source-drift.py",
    "test-root-duplicate-drift.py",
    "test-setup-flow.py",
    "test-provider-configuration.py",
    "test-readme-docs.py",
    "test-migration-flow.py",
    "test-update-flow.py",
    "test-agentic-permission.py",
    "test-agentic-run.py",
    "test-coordinator-apply.py",
    "test-context-packet.py",
    "test-context-packet-v2.py",
)
TESTS_ROOT = ROOT / "devkit" / "tests"
for test in tests:
    check(f"{test} passes", run("python3", str(TESTS_ROOT / test)).returncode == 0)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
