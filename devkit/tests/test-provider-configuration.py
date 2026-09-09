#!/usr/bin/env python3
import json, os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ATLAS = ROOT / "cli" / "atlas"
passed = failed = 0
def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label); passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    home = Path(raw); env = os.environ.copy(); env["ATLAS_HOME"] = str(home)
    cmd = [str(ATLAS), "setup", "--workspace", str(home), "--mode", "personal",
           "--provider", "codex", "--clients", "codex", "--permission-profile", "safe"]
    result = subprocess.run(cmd, env=env, text=True, capture_output=True)
    setup = json.loads((home / "internal/config/setup.json").read_text())
    providers = json.loads((home / "internal/config/providers.json").read_text())
    chk("setup persists selected provider and client", result.returncode == 0
        and setup["provider"] == "codex" and setup["clients"] == ["codex"]
        and providers["primary_provider"] == "codex"
        and providers["providers"][0]["id"] == "codex")
    add = subprocess.run([str(ATLAS), "providers", "add", "gemini"], env=env,
                         text=True, capture_output=True)
    after_add = json.loads(add.stdout)
    chk("providers add preserves primary selection", add.returncode == 0
        and after_add["primary_provider"] == "codex"
        and {p["id"] for p in after_add["providers"]} == {"codex", "gemini"})
    remove = subprocess.run([str(ATLAS), "providers", "remove", "gemini"], env=env,
                            text=True, capture_output=True)
    after_remove = json.loads(remove.stdout)
    chk("providers remove is deterministic", remove.returncode == 0
        and [p["id"] for p in after_remove["providers"]] == ["codex"])

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
