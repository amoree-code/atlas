#!/usr/bin/env python3
"""tests/test-usage-guard-large-results.py — AIOS-017: name the offender, not just the count.

`ai-os usage --guard`'s `large_results` finding already told you a session admitted N raw
tool results over the reporting threshold and how many characters total — but not which
tool call was the biggest one, so acting on "run large or repetitive commands through
`ai-os observe --`" meant re-reading the whole session by hand to find what to wrap. Each
session report already computes `large_results.top` (the biggest offenders, tool + chars),
it just was not surfaced in the guard finding text. This test proves the finding now names
the largest offending tool and its size, and still fires under exactly the same trigger
condition (>= 5 large results) as before — no threshold, no other finding, changed.

Like `test-context-next-mode.py`, this exercises the live, dispatched Atlas copy directly
(`~/atlas/context/ai-os-usage` — usage's canonical implementation since T-017; the
`engine/cli/ai-os-usage` copy is historical and no longer invoked), and is skipped, not
failed, on a machine where that copy does not exist.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LIVE_USAGE = Path(os.environ.get("ATLAS_HOME", str(Path.home() / "atlas"))) / "context" / "ai-os-usage"

G, R, D, X = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = R = D = X = ""
passed = failed = 0


def chk(desc, ok):
    global passed, failed
    if ok:
        print(f"  {G}PASS{X} {desc}"); passed += 1
    else:
        print(f"  {R}FAIL{X} {desc}"); failed += 1


def t(label):
    print(f"\n{D}— {label}{X}")


if not LIVE_USAGE.is_file():
    print("  (skipped — no ~/atlas/context/ai-os-usage found on this machine; nothing "
          "to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)


def usage_line(n, tool, input_field):
    payload = json.dumps({"input_tokens": 0, "cache_read_input_tokens": 100,
                          "cache_creation_input_tokens": 10,
                          "cache_creation": {"ephemeral_5m_input_tokens": 10,
                                             "ephemeral_1h_input_tokens": 0},
                          "output_tokens": 5,
                          "output_tokens_details": {"thinking_tokens": 1}})
    return (json.dumps({"type": "assistant", "sessionId": "BIGOUT",
                        "timestamp": "2026-09-07T00:00:0%dZ" % (n % 10), "cwd": "/w",
                        "message": {"id": f"m{n}", "model": "claude-sonnet-5",
                                   "usage": json.loads(payload),
                                   "content": [{"type": "tool_use", "id": f"tu{n}",
                                               "name": tool, "input": input_field}]}})
            + "\n")


def result_line(n, chars):
    return json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"tu{n}", "content": "x" * chars}]}}) + "\n"


def run(transcripts_dir, *args):
    env = dict(os.environ)
    env.pop("AI_OS_HOME", None)
    return subprocess.run([sys.executable, str(LIVE_USAGE), "--transcripts",
                          str(transcripts_dir), *args], capture_output=True, text=True, env=env)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "transcripts" / "p"
    root.mkdir(parents=True)

    # Five large results (>= 8,000 chars, the reporting threshold), four small Read calls
    # and one much bigger Bash call — the finding should name Bash as the largest.
    lines = []
    for i in range(1, 5):
        lines.append(usage_line(i, "Read", {"file_path": f"/w/f{i}.txt"}))
        lines.append(result_line(i, 9000))
    lines.append(usage_line(5, "Bash", {"command": "make test"}))
    lines.append(result_line(5, 50000))
    (root / "BIGOUT.jsonl").write_text("".join(lines))

    t("guard names the largest offending tool and its size")
    out = run(root, "--guard")
    chk("exits 0 — a warning is not a failure", out.returncode == 0)
    chk("fires the large_results finding", "large_results" in (out.stdout + out.stderr)
        or "5 tool results" in out.stdout)
    chk("names Bash as the largest offender", "largest was Bash" in out.stdout)
    chk("reports its exact size", "50,000 chars" in out.stdout)
    chk("still recommends `ai-os observe --`", "ai-os observe --" in out.stdout)
    chk("points at the offending tool specifically",
        "start with the Bash calls" in out.stdout)

    t("machine-readable output carries the same detail")
    j = run(root, "--json")
    chk("exits 0", j.returncode == 0)
    data = json.loads(j.stdout)
    findings = [g for g in data["guard"] if g["code"] == "large_results"]
    chk("finding present in --json", len(findings) == 1)
    if findings:
        chk("the 'observed' text names Bash as largest",
            "largest was Bash" in findings[0]["observed"])

    t("a cohort under the count threshold still fires no large_results finding")
    small_root = Path(tmp) / "small" / "p"
    small_root.mkdir(parents=True)
    small_lines = []
    for i in range(1, 4):
        small_lines.append(usage_line(i, "Read", {"file_path": f"/w/f{i}.txt"}))
        small_lines.append(result_line(i, 9000))
    (small_root / "SMALLOUT.jsonl").write_text("".join(small_lines))
    out2 = run(small_root, "--guard")
    chk("exits 0", out2.returncode == 0)
    chk("fewer than 5 large results: no large_results finding fires",
        "largest was" not in out2.stdout)

print(f"\n  {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
