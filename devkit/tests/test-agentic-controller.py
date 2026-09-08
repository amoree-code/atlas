#!/usr/bin/env python3
"""T-106: the Agentic controller lifecycle and reference-only routing boundary."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli" / "atlas-agentic"
passed = failed = 0

def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label)
    passed += ok
    failed += not ok

def run(home, *args):
    return subprocess.run([str(CLI), *args], cwd=home, text=True,
        capture_output=True, env={"ATLAS_HOME": str(home), "ATLAS_HOME": str(home),
                                  "PATH": "/usr/bin:/bin"})

with tempfile.TemporaryDirectory() as raw:
    home = Path(raw)
    r = run(home, "create", "--ticket", "T-106", "--summary", "controller test",
            "--surface", "ide", "--scope", "projects/atlas")
    chk("create accepts an explicit surface", r.returncode == 0)
    files = list((home / "runtime/agentic").glob("*.json"))
    chk("one controller-owned run record exists", len(files) == 1)
    run_id = files[0].stem
    rec = json.loads(files[0].read_text())
    chk("actor, surface, scope and stop conditions are recorded", 
        rec["actor"]["client"] == "atlas" and rec["surface"] == "ide"
        and rec["claims"]["scope"] == "projects/atlas"
        and bool(rec["stop_conditions"]))

    r = run(home, "capture", run_id, "--kind", "context", "--ref",
            "runtime/context/packet.json", "--classification", "context-packet")
    chk("context capture stores a reference", r.returncode == 0)
    r = run(home, "capture", run_id, "--kind", "artifact", "--ref",
            "projects/atlas/tickets/T-106/design.md", "--classification", "ticket-local")
    chk("artifact capture stores a classified reference", r.returncode == 0)
    rec = json.loads(files[0].read_text())
    chk("capture does not copy source content", len(rec["routing"]) == 2
        and rec["routing"][1]["classification"] == "ticket-local"
        and not (home / "projects").exists())

    r = run(home, "capture", run_id, "--kind", "artifact", "--ref",
            "personal/inbox/secret.md", "--classification", "personal")
    chk("personal inbox is refused", r.returncode != 0)
    r = run(home, "transition", run_id, "--status", "paused", "--reason", "await review",
            "--stage", "review", "--workflow", "review")
    chk("active run can pause", r.returncode == 0)
    r = run(home, "transition", run_id, "--status", "completed", "--reason", "done")
    chk("paused run cannot skip back into completion", r.returncode == 5)
    r = run(home, "transition", run_id, "--status", "active", "--reason", "review resumed")
    chk("paused run can resume", r.returncode == 0)
    r = run(home, "transition", run_id, "--status", "active", "--reason", "execution",
            "--stage", "execute", "--workflow", "execute")
    chk("controller records an execute stage", r.returncode == 0)
    r = run(home, "transition", run_id, "--status", "completed", "--reason", "verified",
            "--stage", "review", "--workflow", "review")
    chk("active run can complete", r.returncode == 0)
    r = run(home, "capture", run_id, "--kind", "context", "--ref", "runtime/x",
            "--classification", "late")
    chk("terminal run refuses further capture", r.returncode == 5)
    rec = json.loads(files[0].read_text())
    chk("lifecycle evidence records every accepted transition", len(rec["events"]) == 4)

    r = run(home, "create", "--ticket", "T-106", "--summary", "stop test")
    stop_id = max((home / "runtime/agentic").glob("*.json"), key=lambda p: p.stat().st_mtime).stem
    r = run(home, "transition", stop_id, "--status", "stopped", "--reason", "owner stop")
    chk("active run can stop explicitly", r.returncode == 0)
    r = run(home, "capture", stop_id, "--kind", "context", "--ref", "runtime/x",
            "--classification", "late")
    chk("stopped run refuses routing", r.returncode == 5)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
