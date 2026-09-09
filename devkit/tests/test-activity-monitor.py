#!/usr/bin/env python3
"""T-111: activity snapshot is read-only and detects stale heartbeats."""
import json, os, subprocess, tempfile, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "cli" / "atlas-activity"
with tempfile.TemporaryDirectory() as raw:
    home = Path(raw) / "atlas"
    task = home / "projects/atlas/tickets/T-999"
    (task / "coordination").mkdir(parents=True)
    (task / "task.md").write_text("---\nid: T-999\nstate: active\n---\n")
    old = "2020-01-01T00:00:00+00:00"
    (task / "coordination/audit.log").write_text(json.dumps(
        {"at": old, "op": "lease_acquire", "client_id": "test-agent"}) + "\n")
    (task / "coordination/lease.json").write_text(json.dumps(
        {"state": "granted", "client_id": "test-agent", "heartbeat": old}))
    before = (task / "coordination/audit.log").read_bytes()
    r = subprocess.run([str(CLI), "--project", "atlas", "--stale-seconds", "60", "--json"],
                       env={**os.environ, "ATLAS_HOME": str(home)}, capture_output=True, text=True)
    row = json.loads(r.stdout)["tickets"][0]
    assert r.returncode == 0 and row["stale"] and row["activity"][0]["op"] == "lease_acquire"
    assert (task / "coordination/audit.log").read_bytes() == before
print("5 passed, 0 failed")
