#!/usr/bin/env python3
import json, os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]; CLI = ROOT / "cli/atlas-update"
passed = failed = 0
def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label); passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    home = Path(raw); cfg = home / "internal/config"; cfg.mkdir(parents=True)
    (cfg / "workspace.yaml").write_text("workspace_version: old\nuser_value: keep\n")
    env = os.environ.copy(); env.update({"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": "/usr/bin:/bin"})
    def run(*args): return subprocess.run([str(CLI), *args], env=env, capture_output=True, text=True)
    chk("check reports an available local update", run("check", "--json").returncode == 0)
    chk("plan is read-only", run("plan", "--json").returncode == 0 and
        (cfg / "workspace.yaml").read_text().startswith("workspace_version: old"))
    chk("apply requires approval", run("apply").returncode != 0)
    r = run("apply", "--approve", "--json"); data = json.loads(r.stdout)
    chk("approved apply updates only workspace metadata", r.returncode == 0 and
        "user_value: keep" in (cfg / "workspace.yaml").read_text() and
        "workspace_version: old" not in (cfg / "workspace.yaml").read_text())
    chk("apply writes a receipt and runs doctor", Path(data["receipt"]).is_file() and "doctor_exit" in data)

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
