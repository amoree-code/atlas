#!/usr/bin/env python3
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(path, name):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ctx = load(ROOT / "cli" / "atlas_context_packet.py", "packet_v2")
core = ctx
packet = {
    "schema": ctx.SCHEMA, "kind": "handoff",
    "root": {"project": "atlas", "ticket": "T-059", "mission": "M-1", "scope": "engine/cli"},
    "budget": {"unit": "tokens", "limit": 1000, "reserved": 100, "used": 500},
    "state": {"status": "active", "next_action": "run tests", "blockers": []},
    "evidence": [{"id": "E-1", "kind": "test", "ref": "test-context-packet-v2.py"}],
}

assert ctx.validate_packet(packet)
assert ctx.canonical_json(packet) == core.canonical_json(packet)
assert ctx.packet_hash(packet) == core.packet_hash(packet)
assert ctx.usage("x" * 9) == {"unit": "chars_proxy", "used": 3, "measured": False}
assert ctx.usage("ignored", 42)["measured"] is True
assert [ctx.budget_decision(n, 100)["decision"] for n in (59, 60, 80, 90)] == [
    "CONTINUE", "RETRIEVE", "COMPACT", "FRESH"]
assert ctx.budget_decision(90, 100, unresolved=True)["decision"] == "BLOCKED"
first = ctx.delivery_receipt(packet)
second = ctx.delivery_receipt(packet, first["packet_id"])
assert first["action"] == "deliver" and second["repeated"] is True
print("context packet v2: PASS")
