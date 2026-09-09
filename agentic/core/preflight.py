"""Deterministic Agentic preflight checks.

This module decides whether a prepared packet may proceed. It does not build context,
choose a model, invoke a client, or send a transport.
"""

import math


DECISIONS = ("CONTINUE", "COMPACT", "BLOCKED")


class PreflightError(ValueError):
    pass


def confirmation_check(run, packet, packet_id):
    """Require a ticket-scoped, lazy-context confirmation for dispatch."""
    confirmation = run.get("confirmation") if isinstance(run, dict) else None
    if not isinstance(confirmation, dict) or confirmation.get("status") != "confirmed":
        raise PreflightError("confirmation_missing")
    tickets = confirmation.get("ticket_ids")
    goal = run.get("goal") or {}
    claims = run.get("claims") or {}
    if not (isinstance(tickets, list) and tickets and all(isinstance(t, str) for t in tickets)):
        raise PreflightError("confirmation_ticket_ids_missing")
    if goal.get("ticket") not in tickets:
        raise PreflightError("confirmation_goal_ticket_missing")
    if confirmation.get("scope_ref") != claims.get("scope"):
        raise PreflightError("confirmation_scope_mismatch")
    if confirmation.get("packet_hash") != packet_id:
        raise PreflightError("confirmation_packet_mismatch")
    policy = confirmation.get("context_policy") or {}
    if policy.get("mode") != "lazy":
        raise PreflightError("context_policy_not_lazy")
    for key in ("token_limit", "cost_limit_usd"):
        _number(confirmation.get(key), f"confirmation_{key}", positive=True)
    return confirmation


def packet_budget(packet, run):
    """Validate that a context packet belongs to the run and return its budget."""
    if not isinstance(packet, dict) or not isinstance(run, dict):
        raise PreflightError("packet and run must be objects")
    root = packet.get("root") or {}
    goal = run.get("goal") or {}
    claims = run.get("claims") or {}
    if root.get("ticket") != goal.get("ticket"):
        raise PreflightError("packet_ticket_mismatch")
    if root.get("scope") != claims.get("scope"):
        raise PreflightError("packet_scope_mismatch")
    budget = packet.get("budget") or {}
    return budget.get("used"), budget.get("limit")


def reconcile_usage(report, actual_cost_usd=None, cost_limit_usd=None):
    """Normalize measured usage JSON and conservatively classify its cost."""
    if not isinstance(report, dict) or not isinstance(report.get("totals"), dict):
        raise PreflightError("usage_report_totals_missing")
    totals = report["totals"]
    fields = ("input", "cache_read", "cache_write", "output", "thinking")
    normalized = {}
    for field in fields:
        value = totals.get(field, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PreflightError(f"usage_{field}_invalid")
        normalized[field] = value
    if actual_cost_usd is not None:
        actual_cost_usd = _number(actual_cost_usd, "actual_cost_usd")
    if cost_limit_usd is not None:
        cost_limit_usd = _number(cost_limit_usd, "cost_limit_usd", positive=True)
    if actual_cost_usd is None:
        cost_status = "unreported"
        reduction_signal = "cost_unreported"
    elif cost_limit_usd is None:
        cost_status = "reported"
        reduction_signal = "budget_unavailable"
    else:
        cost_status = "reported"
        reduction_signal = "over_budget" if actual_cost_usd > cost_limit_usd else "within_budget"
    return {
        "totals": normalized,
        "total_tokens": sum(normalized.values()),
        "weighted_total": report.get("weighted_total"),
        "actual_cost_usd": actual_cost_usd,
        "cost_status": cost_status,
        "reduction_signal": reduction_signal,
    }


def _number(value, name, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PreflightError(f"{name} must be a number")
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise PreflightError(f"{name} must be a finite {'positive ' if positive else ''}number")
    return value


def evaluate(*, used_tokens, token_limit, estimated_cost_usd, cost_limit_usd,
             transport_verified, unresolved=False):
    """Return a fail-closed decision for one already-built packet."""
    used = _number(used_tokens, "used_tokens")
    limit = _number(token_limit, "token_limit", positive=True)
    estimate = _number(estimated_cost_usd, "estimated_cost_usd")
    cost_limit = _number(cost_limit_usd, "cost_limit_usd", positive=True)

    if not transport_verified:
        decision = "BLOCKED"
        reason = "transport_unverified"
    elif unresolved:
        decision = "BLOCKED"
        reason = "context_unresolved"
    elif used > limit:
        decision = "BLOCKED"
        reason = "token_budget_exceeded"
    elif estimate > cost_limit:
        decision = "BLOCKED"
        reason = "cost_budget_exceeded"
    elif used / limit >= 0.80:
        decision = "COMPACT"
        reason = "token_budget_near_limit"
    else:
        decision = "CONTINUE"
        reason = "within_budget"

    return {
        "decision": decision,
        "reason": reason,
        "tokens": {"used": used, "limit": limit,
                    "ratio": round(used / limit, 6)},
        "cost_usd": {"estimated": estimate, "limit": cost_limit,
                      "remaining": round(cost_limit - estimate, 9)},
        "transport_verified": bool(transport_verified),
        "unresolved": bool(unresolved),
    }
