#!/usr/bin/env python3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DOCS = ROOT / "cli" / "atlas-docs"
text = README.read_text()
result = subprocess.run([str(DOCS), "check"], text=True, capture_output=True)
checks = {
    "docs check passes": result.returncode == 0,
    "README has bounded generated markers": "atlas:readme-generated:begin" in text and "atlas:readme-generated:end" in text,
    "README has local setup diagram": "flowchart LR" in text and "atlas setup" in text,
    "README has architecture diagram": "flowchart TB" in text and "Client adapters" in text,
    "README links local docs": "devkit/docs/use/getting-started.md" in text,
    "README links GitDiagram": "https://gitdiagram.com" in text,
}
for label, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + label)
print(f"{sum(checks.values())} passed, {len(checks) - sum(checks.values())} failed")
raise SystemExit(0 if all(checks.values()) else 1)
