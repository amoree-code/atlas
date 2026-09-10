import type { SessionStore } from "../../infrastructure/persistence/session-store.js";
import { assertRunCanStart, type RunContract } from "../../domain/runs/run-contract.js";

export function authorizeRun(store: SessionStore, contract: RunContract, attempt = 1): void {
  try {
    assertRunCanStart(contract, attempt);
    store.appendEvent(contract.sessionId, "run_approval", JSON.stringify({ runId: contract.runId, approved: true, attempt }));
  } catch (error) {
    store.appendEvent(contract.sessionId, "run_refusal", JSON.stringify({ runId: contract.runId, approved: false, reason: error instanceof Error ? error.message : String(error), attempt }));
    throw error;
  }
}
