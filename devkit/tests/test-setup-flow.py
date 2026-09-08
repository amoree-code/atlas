#!/usr/bin/env python3
import os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "cli" / "atlas"
passed = failed = 0
def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label); passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    home = Path(raw); env = os.environ.copy()
    env.update({"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"})
    plan = subprocess.run([str(ATLAS), "setup", "plan"], env=env, text=True, capture_output=True)
    chk("setup plan is read-only", plan.returncode == 0 and not (home / "runtime").exists()
        and "approval" in plan.stdout)
    no = subprocess.run([str(ATLAS), "setup", "apply"], env=env, text=True, capture_output=True)
    chk("setup apply requires approval", no.returncode == 2 and not (home / "runtime").exists())
    yes = subprocess.run([str(ATLAS), "setup", "apply", "--approve"], env=env, text=True, capture_output=True)
    chk("approved setup initializes Atlas and stops for missing onboarding data", yes.returncode == 1
        and (home / "runtime/dispatch-inbox").is_dir() and "FAIL" in yes.stdout)
    chk("setup does not create a legacy root", not (home / "atlas").exists())

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
