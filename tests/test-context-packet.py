#!/usr/bin/env python3
"""Small contract checks for the derived JSON context packet."""
import importlib.util
import json
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(path, name):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ctx = load(ROOT / "cli" / "ai-os-context", "context_packet_under_test")
core_ctx = load(ROOT.parent / "core" / "cli" / "ai-os-context", "core_context_packet_under_test")
packet = {
    "project": "ai-os",
    "project_dir": "/tmp/ai-os",
    "tickets_live": [
        {"id": "T-059", "state": "todo", "title": "Context optimization",
         "next_action": "write the packet contract", "record": "/tmp/T-059",
         "objective": "reduce repeated context and token waste"},
        {"id": "T-057", "state": "active", "title": "Channel pilots",
         "next_action": "prove separate scopes", "record": "/tmp/T-057",
         "objective": "test channels"},
    ],
    "focus": {"id": "T-059", "state": "todo", "title": "Context optimization",
              "next_action": "write the packet contract", "record": "/tmp/T-059",
              "objective": "reduce repeated context and token waste",
              "verification": "not run", "recent_log": ["x" * 2000]},
    "repos": [{"path": "/tmp/ai-os", "branch": "main", "head": "abc", "uncommitted": 2}],
    "read_next": {"one ticket in full": "ai-os context T-059", "every ticket": "ai-os tickets list"},
}

retrieved = ctx.retrieve(json.loads(json.dumps(packet)), "context token")
assert retrieved["retrieval"]["matches"] == ["T-059"]
assert [t["id"] for t in retrieved["tickets_live"]] == ["T-059"]

compact = ctx.compact_packet(packet, 700)
assert compact["packet"]["schema"] == "atlas.context.packet.v1"
assert compact["packet"]["compacted"] is True
assert compact["packet"]["returned_chars"] <= 700
assert compact["focus"]["next_action"] == "write the packet contract"
assert compact["packet"]["original_chars"] > compact["packet"]["returned_chars"]

try:
    ctx.compact_packet(packet, 511)
except ValueError:
    pass
else:
    raise AssertionError("budgets below 512 characters must be refused")

core_compact = core_ctx.compact_packet(packet, 700)
assert core_compact["packet"]["schema"] == "atlas.context.packet.v1"
assert core_compact["packet"]["returned_chars"] <= 700
assert core_compact["focus"]["next_action"] == "write the packet contract"
print("context packet: PASS")
