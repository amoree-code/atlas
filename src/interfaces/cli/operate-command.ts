import { atlasRoot } from "../../paths.js";
import { classifyIntent } from "../../application/context/intent-router.js";
import { operationForIntent, type OperationName } from "../../application/operations/operation-contract.js";
import { guardedRunOperation, type GuardScope } from "../../application/operations/write-guard.js";
import { runOperation } from "../../application/operations/record-operations.js";

const OPERATION_BUDGET = { maxFiles: 20, maxBytes: 200_000, maxChars: 50_000, maxOperationCost: 10 };

export async function runOperateCommand(text: string): Promise<void> {
  const classification = classifyIntent(text);
  const mapped = operationForIntent(classification);
  if (!mapped.operation) {
    console.log(JSON.stringify({ classification, operation: null, ok: false, reason: mapped.reason }));
    return;
  }

  const operation = mapped.operation as OperationName;
  const scope: GuardScope = {
    action: operation,
    target: atlasRoot(),
    identifier: classification.identifier ?? null,
    projectId: null,
  };
  const { decision, result } = await guardedRunOperation(
    { sessionId: "cli-operate", classification, scope, budget: OPERATION_BUDGET },
    async (approval) => runOperation(operation, classification, OPERATION_BUDGET, { cwd: process.cwd(), query: text, approval: approval ?? undefined }),
  );

  console.log(JSON.stringify({ classification, operation, decision, ...(result ?? { ok: false, reason: decision.reason }) }));
  if (!decision.allowed || (result && typeof result === "object" && "ok" in result && result.ok === false && operation.endsWith(".write"))) {
    process.exitCode = 2;
  }
}
