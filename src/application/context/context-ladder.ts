import { stat } from "node:fs/promises";
import path from "node:path";
import { atlasPath, atlasRoot, resolveWithin } from "../../paths.js";
import type { IntentClassification } from "./intent-router.js";

// Context ladder: startup identity only -> project metadata -> ranked references -> exact
// record by id. Each rung is resolved deterministically from a slice-4 IntentClassification,
// and no rung above "identity" is ever reached for a low-confidence, ambiguous, or unknown
// classification (fail-closed). No rung here reads file content — it only validates a
// budget and, for "exact-record", stats a single bounded, path-checked candidate file to
// prove size before any later slice is allowed to read it. See T-198 slice 5.
export type LadderRung = "identity" | "project-metadata" | "ranked-references" | "exact-record";

export type ContextBudget = {
  maxFiles: number;
  maxBytes: number;
  maxChars: number;
  maxOperationCost: number;
};

// Hard ceilings: a caller cannot request an arbitrarily large budget and call it "bounded".
// These are generous enough for a single compact read, never for a repository scan.
const BUDGET_CEILING: ContextBudget = { maxFiles: 20, maxBytes: 200_000, maxChars: 50_000, maxOperationCost: 10 };

export type BudgetViolation =
  | "invalid-budget"
  | "max-files-exceeded"
  | "max-bytes-exceeded"
  | "max-chars-exceeded"
  | "max-operation-cost-exceeded"
  | null;

export type BoundedReadResult = {
  rung: LadderRung;
  allowed: boolean;
  reason: string;
  violation: BudgetViolation;
  files: string[];
  bytes: number;
  truncated: boolean;
};

function isBoundedPositiveInteger(value: unknown, ceiling: number): boolean {
  return typeof value === "number" && Number.isInteger(value) && Number.isFinite(value) && value > 0 && value <= ceiling;
}

// Rejects missing, non-numeric, negative, zero, NaN, Infinity, non-integer, and
// oversized-beyond-ceiling budgets. A budget that passes this check is never itself the
// reason a read becomes unbounded.
export function validateBudget(budget: unknown): { valid: true } | { valid: false; reason: string } {
  if (!budget || typeof budget !== "object") return { valid: false, reason: "budget is missing or not an object" };
  const candidate = budget as Partial<ContextBudget>;
  const fields: (keyof ContextBudget)[] = ["maxFiles", "maxBytes", "maxChars", "maxOperationCost"];
  for (const field of fields) {
    const value = candidate[field];
    if (value === undefined) return { valid: false, reason: `budget.${field} is missing` };
    if (!isBoundedPositiveInteger(value, BUDGET_CEILING[field])) {
      return { valid: false, reason: `budget.${field} must be a finite positive integer no greater than ${BUDGET_CEILING[field]} (got ${String(value)})` };
    }
  }
  return { valid: true };
}

const READ_RUNG_COST: Record<LadderRung, number> = { identity: 0, "project-metadata": 1, "ranked-references": 3, "exact-record": 1 };

// Fail-closed: any low confidence, any ambiguity reason, or the "unknown" intent stays at
// "identity" — no project metadata, no reference ranking, no record fetch is attempted.
export function resolveLadderRung(classification: IntentClassification): { rung: LadderRung; reason: string } {
  if (classification.intent === "unknown" || classification.confidence === "low" || classification.ambiguityReason) {
    return { rung: "identity", reason: "low confidence, ambiguous, or unknown intent — failing closed at identity, no read attempted" };
  }
  if (classification.intent === "project-detect") {
    return { rung: "project-metadata", reason: "project-detect intent resolves to project metadata only" };
  }
  if (classification.intent === "ticket-lookup" && classification.identifier) {
    return { rung: "exact-record", reason: "ticket-lookup with an explicit, validated identifier resolves to an exact record" };
  }
  if (classification.intent === "memory-lookup" || classification.intent === "knowledge-lookup" || classification.intent === "decision-lookup") {
    return { rung: "ranked-references", reason: `${classification.intent} has no explicit identifier — resolves to ranked references, not a full record` };
  }
  return { rung: "identity", reason: `intent '${classification.intent}' is a write/execution/create request, not a read — the context ladder does not escalate past identity for it` };
}

function budgetRejection(rung: LadderRung, reason: string, violation: BudgetViolation = "invalid-budget"): BoundedReadResult {
  return { rung, allowed: false, reason, violation, files: [], bytes: 0, truncated: false };
}

function withinCharBudget(result: Omit<BoundedReadResult, "violation" | "allowed" | "reason"> & { reason: string }, budget: ContextBudget, rung: LadderRung): BoundedReadResult {
  const serializedChars = JSON.stringify(result).length;
  if (serializedChars > budget.maxChars) {
    return budgetRejection(rung, `context result is ${serializedChars} chars, budget allows ${budget.maxChars}`, "max-chars-exceeded");
  }
  return { ...result, allowed: true, violation: null };
}

const TICKET_ID_SHAPE = /^T-\d+$/i;

// Only ever resolves a single, already-validated ticket id to its task.md path, and only
// ever stats it (size), never reads its content — the actual compact read is a later slice.
async function planExactTicketRecord(identifier: string, budget: ContextBudget): Promise<BoundedReadResult> {
  const rung: LadderRung = "exact-record";
  if (!TICKET_ID_SHAPE.test(identifier)) {
    return budgetRejection(rung, `'${identifier}' is not a valid ticket identifier shape (expected T-<digits>) — refusing to guess a path`, null);
  }
  const cost = READ_RUNG_COST[rung];
  if (cost > budget.maxOperationCost) {
    return budgetRejection(rung, `exact-record operation cost ${cost} exceeds budget.maxOperationCost ${budget.maxOperationCost}`, "max-operation-cost-exceeded");
  }
  if (1 > budget.maxFiles) {
    return budgetRejection(rung, `a single ticket record requires 1 file, budget.maxFiles is ${budget.maxFiles}`, "max-files-exceeded");
  }
  const normalized = `T-${identifier.replace(/^T-/i, "")}`;
  let resolvedPath: string;
  try {
    resolvedPath = resolveWithin(atlasPath("projects", "atlas", "tickets"), normalized, "task.md");
  } catch {
    return budgetRejection(rung, "resolved ticket path escapes the Atlas ticket root — refusing to read outside scope", null);
  }
  let size: number;
  try {
    size = (await stat(resolvedPath)).size;
  } catch {
    return budgetRejection(rung, `ticket ${normalized} was not found under the Atlas ticket root`, null);
  }
  if (size > budget.maxBytes) {
    return budgetRejection(rung, `ticket ${normalized} is ${size} bytes, budget.maxBytes allows ${budget.maxBytes} — refusing to silently truncate`, "max-bytes-exceeded");
  }
  const relative = path.relative(atlasRoot(), resolvedPath);
  return withinCharBudget({ rung, files: [relative], bytes: size, truncated: false, reason: `ticket ${normalized} is within budget (${size}/${budget.maxBytes} bytes)` }, budget, rung);
}

function planProjectMetadata(budget: ContextBudget): BoundedReadResult {
  const rung: LadderRung = "project-metadata";
  const cost = READ_RUNG_COST[rung];
  if (cost > budget.maxOperationCost) {
    return budgetRejection(rung, `project-metadata operation cost ${cost} exceeds budget.maxOperationCost ${budget.maxOperationCost}`, "max-operation-cost-exceeded");
  }
  return withinCharBudget({ rung, files: [], bytes: 0, truncated: false, reason: "project metadata resolution is deferred to the existing project resolver; no file read performed by the ladder itself" }, budget, rung);
}

function planRankedReferences(intent: string, budget: ContextBudget): BoundedReadResult {
  const rung: LadderRung = "ranked-references";
  const cost = READ_RUNG_COST[rung];
  if (cost > budget.maxOperationCost) {
    return budgetRejection(rung, `ranked-references operation cost ${cost} exceeds budget.maxOperationCost ${budget.maxOperationCost}`, "max-operation-cost-exceeded");
  }
  return withinCharBudget({ rung, files: [], bytes: 0, truncated: false, reason: `budget validated for '${intent}'; ranked-reference search is not implemented by this slice — no read performed` }, budget, rung);
}

// Top-level entry point reused across CLI/shim/hook/MCP callers: resolves the ladder rung
// from a slice-4 classification, validates the budget before touching anything, and stops
// immediately at the first violation with a clear, non-silent reason.
export async function planContextRead(classification: IntentClassification, budget: unknown): Promise<BoundedReadResult> {
  const { rung, reason } = resolveLadderRung(classification);
  const validation = validateBudget(budget);
  if (!validation.valid) return budgetRejection(rung, validation.reason, "invalid-budget");
  const bounded = budget as ContextBudget;

  if (rung === "identity") return { rung, allowed: true, reason, violation: null, files: [], bytes: 0, truncated: false };
  if (rung === "exact-record") return planExactTicketRecord(classification.identifier ?? "", bounded);
  if (rung === "project-metadata") return planProjectMetadata(bounded);
  return planRankedReferences(classification.intent, bounded);
}
