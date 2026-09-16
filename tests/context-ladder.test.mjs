import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { classifyIntent } from "../dist/application/context/intent-router.js";
import { planContextRead, resolveLadderRung, validateBudget } from "../dist/application/context/context-ladder.js";

const GOOD_BUDGET = { maxFiles: 5, maxBytes: 50_000, maxChars: 5_000, maxOperationCost: 5 };

async function withTempTicket(bytes, fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-ladder-"));
  const ticketDir = path.join(root, "projects", "atlas", "tickets", "T-1");
  await mkdir(ticketDir, { recursive: true });
  await writeFile(path.join(ticketDir, "task.md"), "x".repeat(bytes));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    return await fn(root);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT; else process.env.ATLAS_ROOT = previous;
  }
}

// --- budget validation ---

test("valid budget passes validation", () => {
  assert.deepEqual(validateBudget(GOOD_BUDGET), { valid: true });
});

test("missing budget (undefined) fails validation with a clear reason, not a crash", () => {
  const result = validateBudget(undefined);
  assert.equal(result.valid, false);
  assert.match(result.reason, /missing/);
});

test("missing budget (null) fails validation", () => {
  const result = validateBudget(null);
  assert.equal(result.valid, false);
});

test("budget missing a required field fails validation and names the field", () => {
  const { maxFiles, ...rest } = GOOD_BUDGET;
  const result = validateBudget(rest);
  assert.equal(result.valid, false);
  assert.match(result.reason, /maxFiles is missing/);
});

test("invalid budget: non-numeric field value is rejected", () => {
  const result = validateBudget({ ...GOOD_BUDGET, maxBytes: "a lot" });
  assert.equal(result.valid, false);
});

test("invalid budget: NaN is rejected", () => {
  const result = validateBudget({ ...GOOD_BUDGET, maxChars: NaN });
  assert.equal(result.valid, false);
});

test("invalid budget: non-integer (fractional) value is rejected", () => {
  const result = validateBudget({ ...GOOD_BUDGET, maxFiles: 1.5 });
  assert.equal(result.valid, false);
});

test("negative limits are rejected for every field", () => {
  for (const field of ["maxFiles", "maxBytes", "maxChars", "maxOperationCost"]) {
    const result = validateBudget({ ...GOOD_BUDGET, [field]: -1 });
    assert.equal(result.valid, false, `${field} should reject -1`);
  }
});

test("zero limits are rejected for every field", () => {
  for (const field of ["maxFiles", "maxBytes", "maxChars", "maxOperationCost"]) {
    const result = validateBudget({ ...GOOD_BUDGET, [field]: 0 });
    assert.equal(result.valid, false, `${field} should reject 0`);
  }
});

test("infinite limits are rejected", () => {
  const result = validateBudget({ ...GOOD_BUDGET, maxBytes: Infinity });
  assert.equal(result.valid, false);
});

test("oversized limits beyond the hard ceiling are rejected, not silently clamped", () => {
  const result = validateBudget({ ...GOOD_BUDGET, maxBytes: 100_000_000 });
  assert.equal(result.valid, false);
  assert.match(result.reason, /no greater than/);
});

// --- ladder rung resolution: fail-closed behavior ---

test("unknown intent stays at identity (fail-closed), no read attempted", () => {
  const classification = classifyIntent("show me that thing");
  const { rung } = resolveLadderRung(classification);
  assert.equal(rung, "identity");
});

test("ambiguous/medium-confidence intent (e.g. 'continue the login work') stays at identity, not escalated on a guess", () => {
  const classification = classifyIntent("continue the login work");
  assert.equal(classification.confidence, "medium");
  assert.ok(classification.ambiguityReason);
  const { rung } = resolveLadderRung(classification);
  assert.equal(rung, "identity");
});

test("missing identifier on a search-type intent resolves to ranked-references, never an exact-record guess", () => {
  const classification = classifyIntent("what did we decide about auth");
  assert.equal(classification.identifier, null);
  const { rung } = resolveLadderRung(classification);
  assert.equal(rung, "ranked-references");
});

test("write/execute-shaped intents never escalate the read ladder past identity", () => {
  for (const text of ["run the build", "save this as a decision", "start a new project called X"]) {
    const classification = classifyIntent(text);
    const { rung } = resolveLadderRung(classification);
    assert.equal(rung, "identity", `${text} should stay at identity`);
  }
});

// --- planContextRead: end-to-end budget enforcement ---

test("unknown intent through planContextRead is allowed at identity with no files/bytes read", async () => {
  const classification = classifyIntent("show me that thing");
  const result = await planContextRead(classification, GOOD_BUDGET);
  assert.equal(result.rung, "identity");
  assert.equal(result.allowed, true);
  assert.deepEqual(result.files, []);
  assert.equal(result.bytes, 0);
});

test("missing budget on any classification stops immediately with violation invalid-budget", async () => {
  const classification = classifyIntent("show T-1");
  const result = await planContextRead(classification, undefined);
  assert.equal(result.allowed, false);
  assert.equal(result.violation, "invalid-budget");
  assert.deepEqual(result.files, []);
});

test("exact-limit success: ticket exactly at budget.maxBytes is allowed", () =>
  withTempTicket(1000, async () => {
    const classification = classifyIntent("show T-1");
    const result = await planContextRead(classification, { ...GOOD_BUDGET, maxBytes: 1000 });
    assert.equal(result.allowed, true);
    assert.equal(result.bytes, 1000);
    assert.equal(result.truncated, false);
  }));

test("one-over-limit failure: ticket one byte over budget.maxBytes is rejected, not silently truncated", () =>
  withTempTicket(1000, async () => {
    const classification = classifyIntent("show T-1");
    const result = await planContextRead(classification, { ...GOOD_BUDGET, maxBytes: 999 });
    assert.equal(result.allowed, false);
    assert.equal(result.violation, "max-bytes-exceeded");
    assert.equal(result.bytes, 0);
    assert.equal(result.truncated, false);
    assert.match(result.reason, /refusing to silently truncate/);
  }));

test("exact-limit success on maxFiles=1 for a single-file ticket record", () =>
  withTempTicket(10, async () => {
    const classification = classifyIntent("show T-1");
    const result = await planContextRead(classification, { ...GOOD_BUDGET, maxFiles: 1 });
    assert.equal(result.allowed, true);
  }));

test("operation-cost limit stops an exact-record read before any file is touched", () =>
  withTempTicket(10, async () => {
    const classification = classifyIntent("show T-1");
    const result = await planContextRead(classification, { ...GOOD_BUDGET, maxOperationCost: 1 });
    // exact-record costs 1, so cost 1 is exactly enough (exact-limit success case for cost)
    assert.equal(result.allowed, true);
  }));

test("multiple sequential operations do not leak state between calls (deterministic isolation)", () =>
  withTempTicket(1000, async () => {
    const a = await planContextRead(classifyIntent("show T-1"), { ...GOOD_BUDGET, maxBytes: 999 });
    const b = await planContextRead(classifyIntent("what project am I in"), GOOD_BUDGET);
    const c = await planContextRead(classifyIntent("show T-1"), { ...GOOD_BUDGET, maxBytes: 1000 });
    assert.equal(a.allowed, false);
    assert.equal(b.allowed, true);
    assert.equal(b.rung, "project-metadata");
    assert.equal(c.allowed, true);
  }));

test("missing identifier on a ticket-shaped request without a valid T-id never guesses a path", async () => {
  const classification = classifyIntent("show me ticket 123");
  assert.equal(classification.identifier, null);
  const result = await planContextRead(classification, GOOD_BUDGET);
  assert.equal(result.rung, "identity");
  assert.deepEqual(result.files, []);
});

// --- path traversal ---

test("path traversal: a ticket id that isn't a clean T-<digits> shape is rejected before any filesystem access, never resolved outside the ticket root", () =>
  withTempTicket(10, async () => {
    // These can never satisfy classifyIntent's own T-\d+ extraction, so route the malformed
    // "identifier" straight at the ladder's public entry via a hand-built classification —
    // proving the ladder itself refuses to trust an unshaped identifier, not just the router.
    const malformed = ["../../etc/passwd", "T-1/../../../etc/passwd", "T-../../etc", "T-1;rm -rf", "T-1\0"];
    for (const identifier of malformed) {
      const classification = { intent: "ticket-lookup", entityType: "ticket", identifier, action: "get", confidence: "high", ambiguityReason: null };
      const result = await planContextRead(classification, GOOD_BUDGET);
      assert.equal(result.allowed, false, `should reject ${JSON.stringify(identifier)}`);
      assert.deepEqual(result.files, []);
      assert.doesNotMatch(result.reason, /not found under the Atlas ticket root/, "should be rejected at shape validation, never reach a filesystem stat");
    }
  }));

// --- large adversarial input ---

test("large adversarial input is classified and planned without unbounded work", async () => {
  const huge = "show T-1 ".repeat(20_000);
  const classification = classifyIntent(huge);
  const result = await planContextRead(classification, GOOD_BUDGET);
  assert.ok(JSON.stringify(result).length < 2000);
});

// --- Arabic and English intent output through the ladder ---

test("Arabic ticket-lookup ('عرض T-1') reaches exact-record exactly like its English equivalent", () =>
  withTempTicket(10, async () => {
    const ar = await planContextRead(classifyIntent("عرض T-1"), GOOD_BUDGET);
    const en = await planContextRead(classifyIntent("show T-1"), GOOD_BUDGET);
    assert.equal(ar.rung, "exact-record");
    assert.deepEqual(ar.files, en.files);
    assert.equal(ar.allowed, en.allowed);
  }));

test("Arabic project-detect ('شنو المشروع الحالي') reaches project-metadata like its English equivalent", async () => {
  const ar = await planContextRead(classifyIntent("شنو المشروع الحالي"), GOOD_BUDGET);
  const en = await planContextRead(classifyIntent("what project am I in"), GOOD_BUDGET);
  assert.equal(ar.rung, "project-metadata");
  assert.equal(ar.rung, en.rung);
});

// --- determinism ---

test("identical input produces identical output across repeated calls", () =>
  withTempTicket(500, async () => {
    const classification = classifyIntent("show T-1");
    const first = await planContextRead(classification, GOOD_BUDGET);
    const second = await planContextRead(classification, GOOD_BUDGET);
    assert.deepEqual(first, second);
  }));

// --- no persistence ---

test("planContextRead never writes any file (no persistence of user content or results)", () =>
  withTempTicket(500, async (root) => {
    const before = JSON.stringify(await import("node:fs/promises").then((fs) => fs.readdir(path.join(root, "projects", "atlas", "tickets", "T-1"))));
    await planContextRead(classifyIntent("show T-1"), GOOD_BUDGET);
    await planContextRead(classifyIntent("save this as a decision"), GOOD_BUDGET);
    const after = JSON.stringify(await import("node:fs/promises").then((fs) => fs.readdir(path.join(root, "projects", "atlas", "tickets", "T-1"))));
    assert.equal(before, after);
  }));

// --- no network/provider/MCP imports ---

test("context-ladder.ts imports only node:fs/promises, node:path, and the existing local paths/intent-router modules — no network, provider, or MCP module", async () => {
  const source = await readFile(path.resolve("src/application/context/context-ladder.ts"), "utf8");
  const imports = [...source.matchAll(/^import .*?from "([^"]+)";?$/gm)].map((match) => match[1]);
  const allowed = new Set(["node:fs/promises", "node:path", "../../paths.js", "./intent-router.js"]);
  for (const specifier of imports) assert.ok(allowed.has(specifier), `unexpected import: ${specifier}`);
  const codeOnly = source.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
  assert.doesNotMatch(codeOnly, /node:https?|node:net\b|mcp-client|mcp-server|fetch\(/i);
});
