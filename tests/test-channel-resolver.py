#!/usr/bin/env python3
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "engine" / "cli" / "atlas"


def run(*args):
    env = os.environ.copy()
    return subprocess.run([str(ATLAS), "channel", "resolve", *args], cwd="/tmp",
                          env=env, text=True, capture_output=True)


valid = run("--project", "ai-os", "--session", "test-session", "--ticket", "T-053",
            "--mission", "mission/t053-s4-context-20260907",
            "--scope", "engine/cli/ai-os-channel")
assert valid.returncode == 0, valid.stderr
packet = json.loads(valid.stdout)
assert packet["project_id"] == "ai-os"
assert packet["session_id"] == "test-session"
assert packet["ticket_id"] == "T-053"
assert packet["mission_id"].endswith("t053-s4-context-20260907")
assert packet["project_path"].endswith("/projects/ai-os")
assert packet["atlas_root"] == str(ROOT)

for args in (("--project", "../escape", "--session", "s", "--ticket", "T-053",
              "--mission", "mission/t053-s4-context-20260907", "--scope", "engine/cli/ai-os-channel"),
             ("--project", "ai-os", "--session", "../escape", "--ticket", "T-053",
              "--mission", "mission/t053-s4-context-20260907", "--scope", "engine/cli/ai-os-channel"),
             ("--project", "missing", "--session", "s", "--ticket", "T-053",
              "--mission", "mission/t053-s4-context-20260907", "--scope", "engine/cli/ai-os-channel")):
    assert run(*args).returncode != 0

print("7/7 channel resolver checks passed")
