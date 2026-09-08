#!/usr/bin/env python3
import json, os, subprocess, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "cli" / "atlas-migrate"
passed = failed = 0
def chk(label, ok):
    global passed, failed
    print(("PASS " if ok else "FAIL ") + label); passed += bool(ok); failed += not bool(ok)

with tempfile.TemporaryDirectory() as raw:
    base = Path(raw); source, atlas = base / "legacy", base / "atlas"
    (source / "personal").mkdir(parents=True)
    (source / "personal/note.md").write_text("private note")
    (source / "personal/token.env").write_text("secret")
    (source / "projects/demo").mkdir(parents=True)
    (source / "projects/demo/readme.md").write_text("project")
    env = {"ATLAS_HOME": str(atlas), "PATH": "/usr/bin:/bin"}
    def run(*args):
        return subprocess.run([str(CLI), *args], env=env, cwd=base,
                              capture_output=True, text=True)
    plan = run("plan", "--source", str(source), "--json")
    data = json.loads(plan.stdout)
    chk("plan is read-only", plan.returncode == 0 and not atlas.exists())
    chk("plan skips secret-shaped files", any(x["action"] == "skip" for x in data["files"]))
    no = run("apply", "--source", str(source))
    chk("apply requires explicit approval", no.returncode != 0 and not atlas.exists())
    applied = run("apply", "--source", str(source), "--approve", "--json")
    data = json.loads(applied.stdout); receipt = Path(data["receipt"])
    chk("approved apply copies only safe missing files", applied.returncode == 0
        and (atlas / "personal/note.md").read_text() == "private note"
        and (atlas / "projects/demo/readme.md").is_file()
        and not (atlas / "personal/token.env").exists())
    chk("apply writes a receipt", receipt.is_file() and data["created"])
    (atlas / "personal/note.md").write_text("owner edit")
    again = run("apply", "--source", str(source), "--approve", "--json")
    chk("existing destination is preserved", json.loads(again.stdout)["created"] == [])
    bad = run("rollback", "--receipt", str(receipt))
    chk("rollback requires explicit approval", bad.returncode != 0)
    rolled = run("rollback", "--receipt", str(receipt), "--approve", "--json")
    chk("rollback removes only files from its receipt", rolled.returncode == 0
        and (atlas / "personal/note.md").read_text() == "owner edit"
        and not (atlas / "projects/demo/readme.md").exists())

print(f"{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
