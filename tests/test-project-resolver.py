#!/usr/bin/env python3
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATHS = ROOT / "engine" / "cli" / "atlas-paths"


def run(home, *args):
    env = os.environ.copy()
    env["ATLAS_HOME"] = str(home)
    return subprocess.run([str(PATHS), "project", *args], env=env,
                          text=True, capture_output=True)


with tempfile.TemporaryDirectory() as raw:
    home = Path(raw)
    projects = home / "projects"
    (projects / "demo").mkdir(parents=True)
    outside = home / "outside"
    outside.mkdir()
    (projects / "escape").symlink_to(outside, target_is_directory=True)

    valid = run(home, "demo")
    assert valid.returncode == 0 and Path(valid.stdout.strip()).resolve() == (projects / "demo").resolve()
    assert run(home, "missing").returncode == 4
    assert run(home, "../outside").returncode == 2
    assert run(home, "escape").returncode == 3

print("4/4 project resolver checks passed")
