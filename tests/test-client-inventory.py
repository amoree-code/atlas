#!/usr/bin/env python3
"""T-112: inventory is metadata-only and records declared clients safely."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "atlas-integration"
passed = failed = 0

def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label)
    passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    home, adapters = Path(raw) / "atlas", Path(raw) / "adapters"
    home.mkdir()
    (adapters / "known").mkdir(parents=True)
    (adapters / "known/adapter.yaml").write_text(
        "adapter: known\nname: Known Client\ncontract: 1\n"
        "client:\n  detect: [/definitely-not-installed]\n"
        "provides: {}\nwrites: []\nrequires: []\nenforces: []\n")
    env = {**os.environ, "ATLAS_HOME": str(home), "ATLAS_HOME": str(home),
           "ATLAS_ADAPTERS": str(adapters)}
    result = subprocess.run([str(CLI), "inventory"], env=env, cwd=home,
                            capture_output=True, text=True)
    data = json.loads(result.stdout)
    record = home / "runtime/integrations/inventory.json"
    chk("inventory succeeds", result.returncode == 0)
    chk("declared unavailable client is recorded", data["clients"][0]["support"] == "unavailable")
    chk("inventory is explicitly metadata-only", data["privacy"] == "metadata-only")
    chk("inventory record is durable", record.is_file())
    chk("record contains no conversations or secrets", "conversation" not in record.read_text()
        and "token" not in record.read_text().lower())

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
