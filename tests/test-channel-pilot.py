#!/usr/bin/env python3
"""Contract checks for the read-only CLI channel pilot."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "atlas"
COMMON = [
    "--project", "atlas",
    "--session", "t057-s1-pilot-20260907",
    "--ticket", "T-057",
    "--mission", "mission/t057-s1-channel-pilot-20260907",
    "--scope", "projects/atlas/tickets/T-057/T-057-S1-channel-pilot-directive.md",
    "--role", "executor",
    "--approval", "approved",
    "--budget-usd", "0.50",
]


def run(extra):
    result = subprocess.run([str(CLI), "channel", "pilot", *COMMON, *extra], capture_output=True, text=True)
    return result.returncode, json.loads(result.stdout)


def main():
    rc, packet = run(["--provider", "claude-code-mission-pilot", "--capability", "Read"])
    assert rc == 0 and packet["decision"] == "bound"
    assert packet["execution_allowed"] is False

    # T-057: "CLI channel works for Claude and a second provider" — codex is a real,
    # already owner-verified transport (unlike gemini, which has no real tool-restriction
    # flag today; see internal/governance/policies/handoff-transports.yaml). Proving the
    # channel itself is provider-neutral doesn't require gemini specifically. codex holds
    # the planner/verifier roles (see handoff-transports.yaml's roles: map), not executor,
    # so this overrides --role accordingly.
    rc, packet = run(["--role", "planner", "--provider", "codex", "--capability", "Read"])
    assert rc == 0 and packet["decision"] == "bound" and packet["provider"] == "codex"
    assert packet["execution_allowed"] is False

    rc, packet = run(["--provider", "gemini", "--capability", "Read"])
    assert rc == 1 and packet["refusal_reason"] == "provider_mismatch"

    rc, packet = run(["--provider", "claude-code-mission-pilot", "--capability", "Bash"])
    assert rc == 1 and packet["refusal_reason"] == "capability_outside_mission_boundary"

    bad = COMMON.copy()
    bad[bad.index("projects/atlas/tickets/T-057/T-057-S1-channel-pilot-directive.md")] = "../escape"
    result = subprocess.run(
        [str(CLI), "channel", "pilot", *bad, "--provider", "claude-code-mission-pilot", "--capability", "Read"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0

    for channel in ("extension", "desktop"):
        rc, packet = run(["--provider", "claude-code-mission-pilot", "--capability", "Read", "--channel", channel])
        assert rc == 0 and packet["channel"] == channel and packet["execution_allowed"] is False

    # --knowledge-db resolves via os.path.abspath() in atlas-channel-pilot — i.e. relative
    # to the CALLER's cwd, not $ATLAS_HOME. A relative path here only worked when this
    # test happened to be run with $ATLAS_HOME itself as cwd; pass the real, absolute
    # path so the check doesn't depend on incidental invocation directory.
    knowledge_db = str(Path.home() / "atlas" / "runtime" / "knowledge" / "index.sqlite3")
    rc, packet = run([
        "--provider", "claude-code-mission-pilot", "--capability", "Read",
        "--channel", "obsidian", "--note", "architecture/ai-os-roadmap.md",
        "--knowledge-db", knowledge_db,
    ])
    assert rc == 0 and packet["channel"] == "obsidian"

    print("8/8 channel-pilot checks passed")


if __name__ == "__main__":
    main()
