#!/usr/bin/env python3
"""Small T-108 guard for the current Atlas naming boundary."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli"
passed = failed = 0


def check(label, condition):
    global passed, failed
    print(f"  {'PASS' if condition else 'FAIL'} {label}")
    if condition:
        passed += 1
    else:
        failed += 1


def run(name, *args, env=None):
    return subprocess.run([str(CLI / name), *args], text=True,
                          capture_output=True, env={**os.environ, **(env or {})})


with tempfile.TemporaryDirectory() as tmp:
    atlas = Path(tmp) / "atlas"
    (atlas / "personal" / "memory").mkdir(parents=True)
    r = run("atlas", "root", env={"ATLAS_HOME": str(atlas)})
    check("atlas root uses ATLAS_HOME", r.returncode == 0 and
          Path(r.stdout.strip()).resolve() == atlas.resolve())

    legacy = "ai" + "-os"
    check("legacy executable has been removed", not (CLI / legacy).exists())

for name in ("atlas-adapter", "atlas-capability", "atlas-memory", "atlas-render", "atlas-run"):
        source = (CLI / name).read_text()
        check(f"{name} defaults to Atlas when ATLAS_HOME is absent",
              'os.environ.get("ATLAS_HOME"' in source or '"$HOME/atlas"' in source)

for rel in ("extensions/skills/catch-up/SKILL.md", "extensions/skills/day-start/SKILL.md",
            "extensions/skills/session-handoff/SKILL.md",
            "extensions/skills/workspace-health/SKILL.md"):
    text = (ROOT.parent / rel).read_text()
    check(f"{rel} uses current Atlas command guidance", legacy + " context" not in text)
    check(f"{rel} does not point at the deleted legacy home", "~/." + legacy not in text)

historical = ROOT.parent / "projects" / "atlas" / "tickets" / "archive" / "Atlas" / "T-108" / "task.md"
check("historical T-108 identity remains unchanged", historical.is_file())
print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
