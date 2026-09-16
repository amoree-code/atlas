import assert from "node:assert/strict";
import test from "node:test";
import { validateSessionEntryContract } from "../dist/domain/sessions/entry-contract.js";

test("validates the full-head entry contract", () => {
  assert.deepEqual(validateSessionEntryContract({
    entryPoint: "atlas-run",
    controlLevel: "full-head",
    inputCapture: "semantic",
    contextTransport: "profile-context-and-provider-adapter",
    policyEnforcement: "profile-and-run-contract",
    promotion: "explicit-review",
    resume: "provider-session-id",
  }).controlLevel, "full-head");
});

test("rejects an entry contract that promises an unknown control level", () => {
  assert.throws(() => validateSessionEntryContract({
    entryPoint: "terminal-shim",
    controlLevel: "unsupported",
    inputCapture: "bounded-terminal",
    contextTransport: "manifest-only",
    policyEnforcement: "shim-lifecycle-and-provider-owned-policy",
    promotion: "explicit-review",
    resume: "unsupported",
  }), /Invalid enum value/);
});
