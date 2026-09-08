#!/usr/bin/env python3
"""T-115: the final CLI name, isolated root resolution and historical identities."""
import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "cli"
passed = 0


def check(label, ok):
    global passed
    assert ok, label
    passed += 1
    print("PASS", label)


def run(name, *args, env=None):
    return subprocess.run([str(CLI / name), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


r = run("atlas", "version")
check("version executes", r.returncode == 0)
check("version is authoritative", r.stdout.strip() == (REPO / "VERSION").read_text().strip())
r = run("atlas", "help")
check("help names Atlas", r.returncode == 0 and "atlas v" in r.stdout)
legacy = "ai" + "-os"
check("legacy CLI removed", not (CLI / legacy).exists())
check("help does not advertise the removed CLI", legacy not in r.stdout)
check("unknown command is refused", run("atlas", "frobnicate").returncode == 2)

with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    home.mkdir()
    (home / "atlas").mkdir()
    root = Path(tmp) / "workspace"
    (root / "personal/memory").mkdir(parents=True)
    env = {"HOME": str(home), "ATLAS_HOME": str(root)}
    r = run("atlas", "root", env=env)
    check("explicit root is selected", r.returncode == 0 and Path(r.stdout.strip()).resolve() == root.resolve())
    r = run("atlas-paths", "get", "memory", env=env)
    check("custom workspace never uses real user memory",
          r.returncode == 0 and r.stdout.strip() == str(root / "personal/memory"))
    r = run("atlas", "root", env={"HOME": str(home), "ATLAS_HOME": ""})
    check("unset root uses Atlas below isolated HOME",
          r.returncode == 0 and Path(r.stdout.strip()).resolve() == (home / "atlas").resolve())
    r = run("atlas", "root", env={"HOME": str(home), "ATLAS_HOME": "",
                                  "AI" + "_OS_HOME": str(root)})
    check("retired environment variable is ignored",
          r.returncode == 0 and Path(r.stdout.strip()).resolve() == (home / "atlas").resolve())

r = run("atlas-paths", "ticket", "AIOS-001")
check("historical identity still resolves", r.returncode == 0 and (Path(r.stdout.strip()) / "task.md").is_file())
r = run("atlas-tickets", "doctor", "--project", "atlas")
check("ticket authority has no errors", r.returncode == 0 and "0 error(s)" in r.stdout)
r = run("atlas", "doctor", "--quiet")
check("doctor recognizes the approved engine placement",
      "public is nested inside private" not in r.stdout and
      "nested git repository inside the private workspace" not in r.stdout)
print(f"{passed} passed, 0 failed")
