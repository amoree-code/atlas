#!/usr/bin/env python3
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def block(text, marker):
    start = text.index(marker)
    return text[start:]


transports = (ROOT / "engine/internal/governance/policies/handoff-transports.yaml").read_text()
gemini_transport = block(transports, "gemini-cli-mission-pilot:")
assert "adapter: gemini" in gemini_transport
assert "verified: false" in gemini_transport
gemini_argv_line = next(l for l in gemini_transport.splitlines() if l.strip().startswith("argv:"))
# gemini has no real tool-restriction flag today: `gemini --help` marks --allowed-tools
# DEPRECATED and describes it as controlling confirmation prompts, not which tools can
# run — not the substring "--tools, Read" this test previously expected. Asserting its
# absence from the actual argv (evidence: below is free to explain the history in
# prose, which does mention the deprecated flag by name).
assert "--allowed-tools" not in gemini_argv_line
assert "__MISSION_SCOPE_DIR__" in gemini_transport
assert "timeout: 300" in gemini_transport

gemini = (ROOT / "engine/adapters/gemini/adapter.yaml").read_text()
assert "consumer_verified: false" in gemini
assert "writes: []" in gemini

fixture = (ROOT / "engine/adapters/atlas-fixture/adapter.yaml").read_text()
assert "adapter: atlas-fixture" in fixture
assert "contract: 1" in fixture
assert "provides: {}" in fixture
assert "writes: []" in fixture
assert "consumer_verified: false" in fixture

spec = importlib.util.spec_from_file_location("atlas_mission", ROOT / "engine/cli/aios_mission.py")
mission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mission)
assert mission.MISSION_PILOT_BUDGET_PLACEHOLDER == "__MISSION_BUDGET_USD__"
scope = {"canonical": str(ROOT / "engine/tests/test-provider-neutral-registry.py")}
argv = mission.build_mission_pilot_argv(
    "gemini",
    [mission.MISSION_PILOT_SCOPE_DIR_PLACEHOLDER, "--max-budget-usd",
     mission.MISSION_PILOT_BUDGET_PLACEHOLDER],
    scope,
    0.50,
)
assert argv[-1] == "0.50"

print("5/5 provider-neutral registry checks passed")
