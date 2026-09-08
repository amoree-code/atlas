"""Pure JSON context-packet primitives; no filesystem, client, or transport dependency."""
import hashlib
import json
import math


SCHEMA = "atlas.context.packet.v2"
DECISIONS = ("CONTINUE", "RETRIEVE", "COMPACT", "FRESH", "BLOCKED")


class PacketError(ValueError):
    pass


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def packet_hash(packet):
    return "sha256:" + hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()


def _require_mapping(packet, key):
    value = packet.get(key)
    if not isinstance(value, dict):
        raise PacketError(f"packet.{key} must be an object")
    return value


def validate_packet(packet):
    if not isinstance(packet, dict):
        raise PacketError("packet must be an object")
    if packet.get("schema") != SCHEMA:
        raise PacketError(f"packet.schema must be {SCHEMA!r}")
    if packet.get("kind") not in ("state", "summary", "retrieval", "handoff"):
        raise PacketError("packet.kind is invalid")
    root = _require_mapping(packet, "root")
    for key in ("project", "ticket", "mission", "scope"):
        if not isinstance(root.get(key), str) or not root[key].strip():
            raise PacketError(f"packet.root.{key} is required")
    budget = _require_mapping(packet, "budget")
    if budget.get("unit") not in ("tokens", "chars_proxy"):
        raise PacketError("packet.budget.unit must be tokens or chars_proxy")
    for key in ("limit", "reserved", "used"):
        if not isinstance(budget.get(key), (int, float)) or budget[key] < 0:
            raise PacketError(f"packet.budget.{key} must be non-negative")
    if budget["limit"] <= 0 or budget["used"] > budget["limit"]:
        raise PacketError("packet budget is outside its declared limit")
    state = _require_mapping(packet, "state")
    if not isinstance(state.get("status"), str) or not state["status"].strip():
        raise PacketError("packet.state.status is required")
    if not isinstance(state.get("next_action"), str):
        raise PacketError("packet.state.next_action is required")
    if not isinstance(state.get("blockers", []), list):
        raise PacketError("packet.state.blockers must be a list")
    if not isinstance(packet.get("evidence", []), list):
        raise PacketError("packet.evidence must be a list")
    return True


def usage(text, token_usage=None):
    """Return measured tokens when available; otherwise a labelled char proxy."""
    if isinstance(token_usage, int) and token_usage >= 0:
        return {"unit": "tokens", "used": token_usage, "measured": True}
    return {"unit": "chars_proxy", "used": math.ceil(len(text) / 4), "measured": False}


def budget_decision(used, limit, unresolved=False):
    if not isinstance(used, (int, float)) or not isinstance(limit, (int, float)):
        raise ValueError("used and limit must be numeric")
    if limit <= 0 or used < 0:
        raise ValueError("used and limit must be non-negative and limit must be positive")
    ratio = used / limit
    if ratio < 0.60:
        decision = "CONTINUE"
    elif ratio < 0.80:
        decision = "RETRIEVE"
    elif ratio < 0.90:
        decision = "COMPACT"
    elif unresolved:
        decision = "BLOCKED"
    else:
        decision = "FRESH"
    return {"decision": decision, "ratio": round(ratio, 6),
            "used": used, "limit": limit, "unresolved": bool(unresolved)}


def delivery_receipt(packet, previous_packet_id=None):
    validate_packet(packet)
    packet_id = packet_hash(packet)
    repeated = packet_id == previous_packet_id if previous_packet_id else False
    return {"packet_id": packet_id, "repeated": repeated,
            "action": "suppress" if repeated else "deliver"}
