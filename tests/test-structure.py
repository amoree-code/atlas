"""Verify adoption, data preservation, and the real dispatcher readiness gate."""
import json
import os
import subprocess
import tempfile
from pathlib import Path

CLI = Path(__file__).resolve().parents[1] / "cli/atlas"
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "atlas"
    env = dict(os.environ, ATLAS_HOME=str(root))
    def run(*args):
        return subprocess.run(["bash", str(CLI), *args], env=env,
                              capture_output=True, text=True)
    assert run("structure", "plan").returncode == 0 and not root.exists()
    assert run("structure", "apply").returncode != 0 and not root.exists()
    (root / "config").mkdir(parents=True)
    owned = root / "config/owned.txt"
    owned.write_text("keep me")
    assert run("structure", "apply", "--approve").returncode == 0
    assert (root / "system/config/owned.txt").read_text() == "keep me"
    marker = root / ".atlas-workspace.json"
    before = marker.read_bytes()
    assert run("structure", "apply", "--approve").returncode == 0
    assert marker.read_bytes() == before and owned.read_text() == "keep me"
    assert run("root").returncode == 0
    marker.write_text("{}")
    assert run("root").returncode != 0
    assert run("structure", "apply", "--approve").returncode != 0
    assert marker.read_text() == "{}"
    marker.write_bytes(before)
    (root / "clients").rmdir()
    assert run("root").returncode != 0
    assert run("structure", "apply", "--approve").returncode == 0
    assert run("root").returncode == 0
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "fresh"
    env = dict(os.environ, ATLAS_HOME=str(root))
    assert run("init").returncode == 0
    profile = root / "internal/config/profile.yaml"
    before = profile.read_bytes()
    assert not (root / "runtime").exists()
    assert run("structure", "apply", "--approve").returncode == 0
    assert (root / "config/profile.yaml").read_bytes() == before
    assert (root / "runtime").samefile(root / "internal/runtime")
    assert (root / "runtime/dispatch-inbox").is_dir()
    paths = subprocess.run([str(CLI.parent / "atlas-paths"), "check"], env=env,
                           capture_output=True, text=True)
    assert paths.returncode == 0, paths.stdout + paths.stderr
    assert run("structure", "check").returncode == 0
    assert run("init").returncode == 0
    assert profile.read_bytes() == before

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "conflict"
    env = dict(os.environ, ATLAS_HOME=str(root))
    (root / "internal/config").mkdir(parents=True)
    (root / "config").mkdir()
    assert run("structure", "apply", "--approve").returncode != 0
    assert not (root / ".atlas-workspace.json").exists()
print("Structure adoption, init parity, idempotence, preservation, and refusal: PASS")
