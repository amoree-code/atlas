#!/usr/bin/env python3
"""T-107: provider-neutral detection and bounded integration records."""
import json, os, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "cli" / "atlas-integration"
passed = failed = 0

def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label)
    passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    home, adapters = Path(raw), Path(raw) / "adapters"
    (adapters / "known").mkdir(parents=True)
    (adapters / "known/adapter.yaml").write_text(
        "adapter: known\nname: Known\ncontract: 1\n"
        "client:\n  detect: [/definitely-not-installed]\n"
        "provides: {}\nwrites: []\nrequires: []\nenforces: []\n")
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home),
           "ATLAS_ADAPTERS": str(adapters), "PATH": "/usr/bin:/bin"}
    def run(*args):
        return subprocess.run([str(CLI), *args], env=env, cwd=home,
                              capture_output=True, text=True)

    r = run("detect", "--client", "known", "--surface", "ide", "--channel", "extension")
    data = json.loads(r.stdout)
    chk("known client is detected but unavailable when its declared path is absent",
        r.returncode == 0 and data["detection"] == "detected" and data["support"] == "unavailable")
    r = run("detect", "--client", "future-ai", "--surface", "terminal")
    data = json.loads(r.stdout)
    chk("unknown client is explicit unsupported, never guessed supported",
        data["support"] == "unsupported" and data["detection"] == "detected")
    r = run("register", "--client", "future-ai", "--surface", "desktop", "--channel", "api")
    data = json.loads(r.stdout)
    record = home / "runtime/integrations/future-ai--desktop--api.json"
    chk("unknown client gets a bounded integration record", r.returncode == 0
        and record.is_file() and data["support"] == "unsupported")
    chk("record contains no client-home or conversation content",
        "~/." not in record.read_text() and "conversation" not in record.read_text())
    listed = json.loads(run("list").stdout)
    chk("list returns the registered record", len(listed) == 1 and listed[0]["client"] == "future-ai")
    r = run("register", "--client", "future-ai", "--surface", "ide", "--channel", "bad")
    chk("unknown channel is refused", r.returncode != 0)

print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
