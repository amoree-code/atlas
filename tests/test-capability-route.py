#!/usr/bin/env python3
"""Small contract checks for the read-only capability router."""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "cli" / "atlas"


def run(*args):
    result = subprocess.run([str(CLI), "capability-route", *args], capture_output=True, text=True)
    assert result.stdout.count("\n") == 1, result.stdout
    return result.returncode, json.loads(result.stdout)


COMMON = [
    "--project", "atlas",
    "--task", "T-055",
    "--role", "executor",
    "--capability", "code_edit",
    "--approval", "approved",
    "--budget-usd", "0.50",
]


def main():
    rc, decision = run(*COMMON, "--available", "claude:code_edit")
    assert rc == 0 and decision["decision"] == "routed"
    assert decision["selected_provider"] == "claude"
    assert decision["fallback_used"] is False

    rc, decision = run(
        *COMMON,
        "--available", "claude:code_edit;gemini:code_edit",
        "--preference", "gemini",
    )
    assert rc == 0 and decision["selected_provider"] == "gemini"

    rc, decision = run(
        *COMMON,
        "--available", "claude:code_edit",
        "--preference", "gemini",
    )
    assert rc == 1 and decision["refusal_reason"] == "preferred_provider_unavailable"

    rc, decision = run(
        *COMMON,
        "--available", "claude:code_edit",
        "--preference", "gemini",
        "--fallback", "true",
    )
    assert rc == 0 and decision["selected_provider"] == "claude"
    assert decision["fallback_used"] is True

    rc, decision = run(
        *COMMON,
        "--available", "claude:code_edit;gemini:code_edit",
    )
    assert rc == 1 and decision["refusal_reason"] == "ambiguous_provider_selection"

    rc, decision = run(*COMMON[:8], "--available", "claude:code_edit")
    assert rc == 1 and decision["refusal_reason"] == "missing_required_field:approval"

    print("6/6 capability-route checks passed")


if __name__ == "__main__":
    main()
