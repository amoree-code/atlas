#!/usr/bin/env python3
import importlib.util
import json
import os
import subprocess
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
path = ROOT / "agentic" / "core" / "preflight.py"
spec = importlib.util.spec_from_loader("agentic_preflight", SourceFileLoader("agentic_preflight", str(path)))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ok = mod.evaluate(used_tokens=500, token_limit=1000, estimated_cost_usd=0.05,
                  cost_limit_usd=0.10, transport_verified=True)
assert ok["decision"] == "CONTINUE"

run = {"goal": {"ticket": "T-122"}, "claims": {"scope": "engine/cli"}}
packet = {"root": {"ticket": "T-122", "scope": "engine/cli"},
          "budget": {"used": 500, "limit": 1000}}
assert mod.packet_budget(packet, run) == (500, 1000)
usage = {"totals": {"input": 100, "cache_read": 20, "cache_write": 10,
                      "output": 30, "thinking": 5}, "weighted_total": 170.0}
reconciled = mod.reconcile_usage(usage, actual_cost_usd=0.08, cost_limit_usd=0.10)
assert reconciled["total_tokens"] == 165
assert reconciled["reduction_signal"] == "within_budget"
assert mod.reconcile_usage(usage)["reduction_signal"] == "cost_unreported"
try:
    mod.packet_budget({"root": {"ticket": "T-999", "scope": "engine/cli"},
                       "budget": {"used": 500, "limit": 1000}}, run)
except mod.PreflightError as exc:
    assert str(exc) == "packet_ticket_mismatch"
else:
    raise AssertionError("packet ticket mismatch was accepted")

with tempfile.TemporaryDirectory() as home:
    env = os.environ.copy()
    env["ATLAS_HOME"] = home
    cli = ROOT / "cli" / "atlas-agentic"
    created = subprocess.run(
        [str(cli), "create", "--ticket", "T-122", "--summary", "preflight smoke"],
        env=env, text=True, capture_output=True, check=True)
    run_id = next(line.split()[1] for line in created.stdout.splitlines()
                  if "created" in line)
    packet_path = Path(home) / "runtime" / "packets" / run_id / "packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(json.dumps({
        "schema": "atlas.context.packet.v2", "kind": "handoff",
        "root": {"project": "atlas", "ticket": "T-122",
                 "mission": "M-1", "scope": "T-122"},
        "budget": {"unit": "tokens", "limit": 1000, "reserved": 100, "used": 500},
        "state": {"status": "active", "next_action": "test", "blockers": []},
        "evidence": [],
    }))
    confirmed = subprocess.run(
        [str(cli), "confirm", run_id, "--packet-file", str(packet_path),
         "--tickets", "T-122", "--scope-ref", "T-122", "--token-limit", "1000",
         "--cost-limit-usd", "0.10"],
        env=env, text=True, capture_output=True, check=True)
    assert "confirmed" in confirmed.stdout
    checked = subprocess.run(
        [str(cli), "preflight", run_id, "--packet-file", str(packet_path),
         "--estimated-cost-usd", "0.05", "--cost-limit-usd", "0.10",
         "--transport-verified", "true"],
        env=env, text=True, capture_output=True, check=True)
    assert json.loads(checked.stdout)["decision"] == "CONTINUE"
    usage_path = Path(home) / "usage.json"
    usage_path.write_text(json.dumps(usage))
    reconciled_cli = subprocess.run(
        [str(cli), "reconcile", run_id, "--usage-file", str(usage_path),
         "--actual-cost-usd", "0.08", "--cost-limit-usd", "0.10"],
        env=env, text=True, capture_output=True, check=True)
    assert json.loads(reconciled_cli.stdout)["total_tokens"] == 165

with tempfile.TemporaryDirectory() as home:
    env = os.environ.copy()
    env["ATLAS_HOME"] = home
    cli = ROOT / "cli" / "atlas-agentic"
    created = subprocess.run(
        [str(cli), "create", "--ticket", "T-123", "--summary", "confirmation gate"],
        env=env, text=True, capture_output=True, check=True)
    run_id = next(line.split()[1] for line in created.stdout.splitlines()
                  if "created" in line)
    packet_path = Path(home) / "runtime" / "packets" / run_id / "packet.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_text(json.dumps({
        "schema": "atlas.context.packet.v2", "kind": "handoff",
        "root": {"project": "atlas", "ticket": "T-123", "mission": "M-1", "scope": "T-123"},
        "budget": {"unit": "tokens", "limit": 1000, "reserved": 100, "used": 100},
        "state": {"status": "active", "next_action": "test", "blockers": []},
        "evidence": [],
    }))
    refused = subprocess.run(
        [str(cli), "preflight", run_id, "--packet-file", str(packet_path),
         "--estimated-cost-usd", "0.01", "--cost-limit-usd", "0.10",
         "--transport-verified", "true"],
        env=env, text=True, capture_output=True)
    assert refused.returncode == 2
    assert "confirmation_missing" in refused.stderr

compact = mod.evaluate(used_tokens=800, token_limit=1000, estimated_cost_usd=0.05,
                       cost_limit_usd=0.10, transport_verified=True)
assert compact["decision"] == "COMPACT"

assert mod.evaluate(used_tokens=1100, token_limit=1000, estimated_cost_usd=0.05,
                    cost_limit_usd=0.10, transport_verified=True)["reason"] == "token_budget_exceeded"
assert mod.evaluate(used_tokens=500, token_limit=1000, estimated_cost_usd=0.11,
                    cost_limit_usd=0.10, transport_verified=True)["reason"] == "cost_budget_exceeded"
assert mod.evaluate(used_tokens=500, token_limit=1000, estimated_cost_usd=0.05,
                    cost_limit_usd=0.10, transport_verified=False)["reason"] == "transport_unverified"
print("agentic preflight: PASS")
