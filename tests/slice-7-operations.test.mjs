import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readdir,
  readFile,
  rm,
  stat,
  utimes,
  writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { classifyIntent } from "../dist/application/context/intent-router.js";
import { bindProject } from "../dist/application/context/project-resolution.js";
import {
  operationForIntent,
  validateTaskIdentifier,
  validateWriteTarget,
} from "../dist/application/operations/operation-contract.js";
import { runOperation } from "../dist/application/operations/record-operations.js";
import {
  createGrant,
  guardedRunOperation,
} from "../dist/application/operations/write-guard.js";
import { atlasRoot, engineRoot } from "../dist/paths.js";

const BUDGET = {
  maxFiles: 10,
  maxBytes: 50_000,
  maxChars: 5_000,
  maxOperationCost: 5,
};

function taskDoc(id, state = "active", checked = true) {
  const item = checked ? '- "[x] done work"' : '- "[ ] unfinished work"';
  return `---\nkind: task\nid: ${id}\ntitle: Task ${id}\nstate: ${state}\nproject: atlas\ngoal: goal for ${id}\npriority: level_2\nupdated_at: 2026-09-16\n---\n\nchecklist:\n  ${item}\n\n## Objective\nbody of ${id}\n`;
}

function recordDoc(name, description) {
  return `---\nname: ${name}\ndescription: "${description}"\nmetadata:\n  type: note\n  status: current\n  confidence: high\n  updated: 2026-09-16\n---\n\nbody\n`;
}

async function withFixture(fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-slice7-"));
  await mkdir(path.join(root, "projects", "atlas", "tasks", "T-1"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "projects", "atlas", "tasks", "T-1", "task.md"),
    taskDoc("T-1"),
  );
  await mkdir(path.join(root, "projects", "atlas", "tasks", "T-2"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "projects", "atlas", "tasks", "T-2", "task.md"),
    taskDoc("T-2"),
  );
  await mkdir(path.join(root, "personal", "memory"), { recursive: true });
  await writeFile(
    path.join(root, "personal", "memory", "work-style.md"),
    recordDoc("development", "Technical defaults and tooling"),
  );
  await writeFile(
    path.join(root, "personal", "memory", "goals.md"),
    recordDoc("goals", "Long term objectives"),
  );
  await mkdir(path.join(root, "personal", "knowledge", "decisions"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, "personal", "knowledge", "decisions", "adopt-atlas.md"),
    recordDoc("adopt-atlas", "Decision to adopt Atlas"),
  );
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    return await fn(root);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previous;
  }
}

const approval = (operation, target) => ({ approved: true, operation, target });

// ---------------------------------------------------------------- intent → operation map

test("every required intent maps to exactly one operation", () => {
  const cases = [
    ["show T-1", "task.get"],
    ["what do you remember about the client", "memory.search"],
    ["what knowledge do we have about deployments", "knowledge.search"],
    ["what is my work style", "memory.search"],
    ["what project am I in", "project.detect"],
    ["start a new project called demo", "project.create"],
    ["save this as a decision", "knowledge.write"],
    ["remember this", "memory.write"],
    ["what did we decide about auth", "knowledge.search"],
  ];
  for (const [text, expected] of cases) {
    assert.equal(
      operationForIntent(classifyIntent(text)).operation,
      expected,
      text,
    );
  }
});

test("task.create requires explicit title and approval, then creates the next bounded task", async () => {
  await withFixture(async (root) => {
    await bindProject("atlas", root);
    const classification = classifyIntent(
      "create a new task called Improve onboarding",
    );
    assert.equal(classification.intent, "task-create");
    assert.equal(operationForIntent(classification).operation, "task.create");
    const budget = BUDGET;
    const denied = await runOperation("task.create", classification, budget, {
      cwd: root,
    });
    assert.equal(denied.ok, false);
    const target = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-3",
      "task.md",
    );
    const scope = {
      action: "task.create",
      target,
      identifier: null,
      projectId: "atlas",
    };
    const sessionId = "task-create-session";
    const grant = createGrant(sessionId, scope);
    const { decision, result } = await guardedRunOperation(
      { sessionId, classification, scope, budget, grant },
      (approval) =>
        runOperation("task.create", classification, budget, {
          cwd: root,
          content: "Implement onboarding improvements",
          approval,
        }),
    );
    assert.equal(decision.allowed, true, decision.reason);
    assert.equal(result.ok, true, result.reason);
    assert.match(await readFile(target, "utf8"), /title: Improve onboarding/);
  });
});

test("an execution intent maps to no record operation at all", () => {
  const mapped = operationForIntent(classifyIntent("run the build"));
  assert.equal(mapped.operation, null);
});

test("an operation that does not match the classified intent is refused, never coerced", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "memory.write",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
        approval: approval("memory.write", "/x"),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /does not match intent/);
  }));

// ---------------------------------------------------------------- task read operations

test("task.get returns one bounded record with selected fields only", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.equal(result.ok, true);
    assert.equal(result.records.length, 1);
    const record = result.records[0];
    assert.equal(record.identifier, "T-1");
    assert.equal(record.recordType, "task");
    assert.equal(record.sourcePath, "projects/atlas/tasks/T-1/task.md");
    assert.deepEqual(Object.keys(record.fields).sort(), [
      "goal",
      "id",
      "priority",
      "state",
      "title",
      "updated_at",
    ]);
    assert.ok(!("body" in record.fields));
    assert.equal(record.freshness, "current");
    assert.equal(record.confidence, "high");
    assert.ok(record.selectionReason.length > 0);
  }));

test("task.list returns every live task, stably ordered, never the archive directory", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "task.list",
      classifyIntent("continue"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.equal(
      result.ok,
      false,
      "bare 'continue' is ambiguous and must fail closed",
    );
    const listable = {
      intent: "task-lookup",
      entityType: "task",
      identifier: null,
      action: "list",
      confidence: "high",
      ambiguityReason: null,
    };
    const listed = await runOperation("task.list", listable, BUDGET, {
      cwd: root,
    });
    assert.equal(listed.ok, true);
    assert.deepEqual(
      listed.records.map((record) => record.identifier),
      ["T-1", "T-2"],
    );
    assert.ok(
      listed.records.every((record) => !record.sourcePath.includes("archive")),
    );
  }));

test("task.list ordering is stable regardless of filesystem ordering", () =>
  withFixture(async (root) => {
    await mkdir(path.join(root, "projects", "atlas", "tasks", "T-10"), {
      recursive: true,
    });
    await writeFile(
      path.join(root, "projects", "atlas", "tasks", "T-10", "task.md"),
      taskDoc("T-10"),
    );
    const listable = {
      intent: "task-lookup",
      entityType: "task",
      identifier: null,
      action: "list",
      confidence: "high",
      ambiguityReason: null,
    };
    const first = await runOperation("task.list", listable, BUDGET, {
      cwd: root,
    });
    const second = await runOperation("task.list", listable, BUDGET, {
      cwd: root,
    });
    assert.deepEqual(
      first.records.map((r) => r.identifier),
      second.records.map((r) => r.identifier),
    );
  }));

test("task.get on a missing task reports not-found, never a guessed record", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-9999"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /was not found/);
    assert.deepEqual(result.records, []);
  }));

test("task.get freshness reports stale for an old record", () =>
  withFixture(async (root) => {
    const file = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-1",
      "task.md",
    );
    const old = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000);
    await utimes(file, old, old);
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.equal(result.records[0].freshness, "stale");
  }));

// ---------------------------------------------------------------- identifier validation

test("valid and invalid task identifiers are separated deterministically", () => {
  assert.equal(validateTaskIdentifier("T-1").valid, true);
  assert.equal(validateTaskIdentifier("T-0001").valid, true);
  for (const bad of [
    "",
    "T1",
    "TASK-1",
    "T-",
    "t-1x",
    "T-1/../etc",
    "T-1\0",
    null,
    undefined,
    12,
  ]) {
    assert.equal(validateTaskIdentifier(bad).valid, false, String(bad));
  }
});

test("a missing identifier never produces a task.get read", () =>
  withFixture(async (root) => {
    const classification = {
      intent: "task-lookup",
      entityType: "task",
      identifier: null,
      action: "get",
      confidence: "high",
      ambiguityReason: null,
    };
    const result = await runOperation("task.get", classification, BUDGET, {
      cwd: root,
    });
    // Refused at the intent-mapping gate: without an identifier the intent maps to
    // task.list, so an exact-record read is never reachable.
    assert.equal(result.ok, false);
    assert.match(result.reason, /does not match intent|identifier is missing/);
    assert.deepEqual(result.records, []);
  }));

// ---------------------------------------------------------------- memory / knowledge read

test("memory.search returns only personal/memory records — no tasks, no engine files", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "memory.search",
      classifyIntent("what do you remember about goals"),
      BUDGET,
      { cwd: root, query: "goals" },
    );
    assert.equal(result.ok, true);
    assert.ok(result.records.length >= 1);
    assert.ok(
      result.records.every((record) =>
        record.sourcePath.startsWith("personal/memory/"),
      ),
      JSON.stringify(result.records),
    );
    assert.ok(result.records.every((record) => record.recordType === "memory"));
  }));

test("knowledge.search returns only personal/knowledge records", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "knowledge.search",
      classifyIntent("what did we decide about atlas"),
      BUDGET,
      { cwd: root, query: "atlas" },
    );
    assert.equal(result.ok, true);
    assert.ok(
      result.records.every((record) =>
        record.sourcePath.startsWith("personal/knowledge/"),
      ),
    );
  }));

test("search results carry freshness, confidence, and an explicit selection reason", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "memory.search",
      classifyIntent("what do you remember about goals"),
      BUDGET,
      { cwd: root, query: "goals" },
    );
    for (const record of result.records) {
      assert.ok(["current", "stale", "unknown"].includes(record.freshness));
      assert.equal(record.confidence, "high");
      assert.match(record.selectionReason, /goals|index entry/);
    }
  }));

test("search is deduplicated and capped by budget.maxFiles with an explicit truncation violation", () =>
  withFixture(async (root) => {
    for (let index = 0; index < 8; index += 1) {
      await writeFile(
        path.join(root, "personal", "memory", `note-${index}.md`),
        recordDoc(`note-${index}`, "bulk note"),
      );
    }
    const result = await runOperation(
      "memory.search",
      classifyIntent("what do you remember"),
      { ...BUDGET, maxFiles: 3 },
      { cwd: root },
    );
    assert.equal(result.records.length, 3);
    assert.match(result.violations.join(" "), /truncated to maxFiles=3/);
  }));

// ---------------------------------------------------------------- write gating

test("a write is refused without an explicit approval", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      BUDGET,
      {
        cwd: root,
        slug: "new-note",
        content: "hello",
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /no explicit approval/);
  }));

test("a write is refused when the approval names a different operation", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "new-note.md");
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      BUDGET,
      {
        cwd: root,
        slug: "new-note",
        content: "hello",
        approval: approval("knowledge.write", target),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /approval was granted for/);
  }));

test("a write is refused when the approval names a different target path", () =>
  withFixture(async (root) => {
    const wrong = path.join(root, "personal", "memory", "other.md");
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      BUDGET,
      {
        cwd: root,
        slug: "new-note",
        content: "hello",
        approval: approval("memory.write", wrong),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /does not match the resolved destination/);
  }));

test("medium-confidence and low-confidence intents never execute a write", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "new-note.md");
    for (const confidence of ["medium", "low"]) {
      const classification = {
        intent: "remember",
        entityType: "memory",
        identifier: null,
        action: "remember",
        confidence,
        ambiguityReason: null,
      };
      const result = await runOperation(
        "memory.write",
        classification,
        BUDGET,
        {
          cwd: root,
          slug: "new-note",
          content: "x",
          approval: approval("memory.write", target),
        },
      );
      assert.equal(result.ok, false, confidence);
      assert.match(result.reason, /only 'high' may write/);
    }
  }));

test("unknown and ambiguous intents fail closed for both reads and writes", () =>
  withFixture(async (root) => {
    const unknown = classifyIntent("show me that thing");
    const read = await runOperation("task.get", unknown, BUDGET, {
      cwd: root,
    });
    assert.equal(read.ok, false);
    const ambiguous = classifyIntent("continue the login work");
    const write = await runOperation("task.update", ambiguous, BUDGET, {
      cwd: root,
      patch: { state: "done" },
      approval: approval("task.update", "/x"),
    });
    assert.equal(write.ok, false);
  }));

test("an invalid budget blocks every operation, read or write", () =>
  withFixture(async (root) => {
    const read = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      { ...BUDGET, maxBytes: -1 },
      { cwd: root },
    );
    assert.equal(read.ok, false);
    assert.match(read.reason, /invalid-budget/);
    const missing = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      undefined,
      {
        cwd: root,
      },
    );
    assert.equal(missing.ok, false);
    assert.match(missing.reason, /invalid-budget/);
  }));

// ---------------------------------------------------------------- writes that succeed

test("memory.write creates a private record under personal/memory and reports the written path", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "new-note.md");
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      BUDGET,
      {
        cwd: root,
        slug: "new-note",
        content: "an explicit fact",
        approval: approval("memory.write", target),
      },
    );
    assert.equal(result.ok, true, result.reason);
    assert.equal(result.written.sourcePath, "personal/memory/new-note.md");
    const written = await readFile(target, "utf8");
    assert.match(written, /name: new-note/);
    assert.match(written, /an explicit fact/);
  }));

test("knowledge.write stores a decision under the requested knowledge kind", () =>
  withFixture(async (root) => {
    const target = path.join(
      root,
      "personal",
      "knowledge",
      "decisions",
      "use-sqlite.md",
    );
    const result = await runOperation(
      "knowledge.write",
      classifyIntent("save this as a decision"),
      BUDGET,
      {
        cwd: root,
        slug: "use-sqlite",
        kind: "decisions",
        content: "we chose sqlite",
        approval: approval("knowledge.write", target),
      },
    );
    assert.equal(result.ok, true, result.reason);
    assert.equal(
      result.written.sourcePath,
      "personal/knowledge/decisions/use-sqlite.md",
    );
    assert.match(await readFile(target, "utf8"), /type: decision/);
  }));

test("knowledge.write refuses a knowledge kind outside the allow-list", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "knowledge", "secrets", "x.md");
    const result = await runOperation(
      "knowledge.write",
      classifyIntent("save this as a decision"),
      BUDGET,
      {
        cwd: root,
        slug: "x",
        kind: "secrets",
        content: "y",
        approval: approval("knowledge.write", target),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /not an allowed knowledge kind/);
  }));

test("a record write never overwrites an existing record", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "goals.md");
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      BUDGET,
      {
        cwd: root,
        slug: "goals",
        content: "replacement",
        approval: approval("memory.write", target),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /refusing to overwrite/);
    assert.match(await readFile(target, "utf8"), /Long term objectives/);
  }));

test("task.update patches only allow-listed frontmatter fields, atomically", () =>
  withFixture(async (root) => {
    const target = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-1",
      "task.md",
    );
    const classification = {
      intent: "task-lookup",
      entityType: "task",
      identifier: "T-1",
      action: "update",
      confidence: "high",
      ambiguityReason: null,
    };
    const result = await runOperation("task.update", classification, BUDGET, {
      cwd: root,
      patch: { state: "blocked" },
      approval: approval("task.update", target),
    });
    assert.equal(result.ok, true, result.reason);
    assert.match(await readFile(target, "utf8"), /^state: blocked$/m);
    const rejected = await runOperation(
      "task.update",
      classification,
      BUDGET,
      {
        cwd: root,
        patch: { secret: "x" },
        approval: approval("task.update", target),
      },
    );
    assert.equal(rejected.ok, false);
    assert.match(rejected.reason, /not an updatable task field/);
  }));

test("task.complete reuses the governed completion path and refuses unchecked work", () =>
  withFixture(async (root) => {
    const dir = path.join(root, "projects", "atlas", "tasks", "T-3");
    await mkdir(dir, { recursive: true });
    await writeFile(
      path.join(dir, "task.md"),
      taskDoc("T-3", "active", false),
    );
    const classification = {
      intent: "task-lookup",
      entityType: "task",
      identifier: "T-3",
      action: "complete",
      confidence: "high",
      ambiguityReason: null,
    };
    const target = path.join(dir, "task.md");
    const result = await runOperation(
      "task.complete",
      classification,
      BUDGET,
      {
        cwd: root,
        approval: approval("task.complete", target),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /unchecked work/);
  }));

test("task.complete succeeds for a fully checked task", () =>
  withFixture(async (root) => {
    const target = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-2",
      "task.md",
    );
    const classification = {
      intent: "task-lookup",
      entityType: "task",
      identifier: "T-2",
      action: "complete",
      confidence: "high",
      ambiguityReason: null,
    };
    const result = await runOperation(
      "task.complete",
      classification,
      BUDGET,
      {
        cwd: root,
        approval: approval("task.complete", target),
      },
    );
    assert.equal(result.ok, true, result.reason);
  }));

// ---------------------------------------------------------------- project operations

test("project.detect reports the bound project without guessing", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "project.detect",
      classifyIntent("what project am I in"),
      BUDGET,
      { cwd: root },
    );
    assert.equal(result.ok, true);
    assert.equal(result.records[0].identifier, "atlas");
    assert.equal(result.records[0].fields.status, "bound");
  }));

test("project.detect reports unbound for a directory outside any binding", () =>
  withFixture(async () => {
    const outside = await mkdtemp(
      path.join(os.tmpdir(), "atlas-slice7-outside-"),
    );
    const result = await runOperation(
      "project.detect",
      classifyIntent("what project am I in"),
      BUDGET,
      { cwd: outside },
    );
    assert.equal(result.records[0].identifier, "unbound");
  }));

test("project.create requires an explicit absolute path and an approval", () =>
  withFixture(async (root) => {
    const classification = classifyIntent("start a new project called demo");
    const target = path.join(root, "projects", "demo");
    const noPath = await runOperation(
      "project.create",
      classification,
      BUDGET,
      {
        cwd: root,
        approval: approval("project.create", target),
      },
    );
    assert.equal(noPath.ok, false);
    assert.match(noPath.reason, /absolute project path is required/);
    const created = await runOperation(
      "project.create",
      classification,
      BUDGET,
      {
        cwd: root,
        projectPath: path.join(root, "workspace-demo"),
        approval: approval("project.create", target),
      },
    );
    assert.equal(created.ok, true, created.reason);
    assert.ok((await stat(target)).isDirectory());
  }));

test("project.update confirms the active project binding only", () =>
  withFixture(async (root) => {
    const classification = {
      intent: "project-create",
      entityType: "project",
      identifier: "atlas",
      action: "create",
      confidence: "high",
      ambiguityReason: null,
    };
    const result = await runOperation(
      "project.update",
      classification,
      BUDGET,
      {
        cwd: root,
        projectPath: root,
        approval: approval(
          "project.update",
          path.join(root, "projects", "atlas"),
        ),
      },
    );
    assert.equal(
      result.ok,
      false,
      "project.update must not accept a project-create classification",
    );
  }));

// ---------------------------------------------------------------- scope and path safety

test("a cross-project request is refused explicitly", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
        requestedProject: "other-project",
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /cross-project request refused/);
  }));

test("private Atlas content is never written inside the public engine package", () => {
  const engineRelative = path
    .relative(atlasRoot(), engineRoot())
    .split(path.sep);
  const rejected = validateWriteTarget(...engineRelative, "src", "leak.md");
  assert.equal(rejected.valid, false);
  assert.match(rejected.reason, /public engine package/);
});

test("write targets that escape the Atlas root are refused", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-escape-"));
  const previous = process.env.ATLAS_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    const rejected = validateWriteTarget("..", "..", "etc", "passwd");
    assert.equal(rejected.valid, false);
    assert.match(rejected.reason, /escapes the Atlas root/);
  } finally {
    if (previous === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previous;
  }
});

test("path traversal, absolute paths, null bytes, and shell syntax are all refused in write slugs", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "x.md");
    for (const slug of [
      "../../etc/passwd",
      "/etc/passwd",
      "note\0",
      "note; rm -rf /",
      "note$(whoami)",
      "a/b",
    ]) {
      const result = await runOperation(
        "memory.write",
        classifyIntent("remember this"),
        BUDGET,
        {
          cwd: root,
          slug,
          content: "x",
          approval: approval("memory.write", target),
        },
      );
      assert.equal(result.ok, false, slug);
      assert.match(result.reason, /write refused/);
    }
  }));

test("traversal in a task identifier never resolves outside the task root", () =>
  withFixture(async (root) => {
    const classification = {
      intent: "task-lookup",
      entityType: "task",
      identifier: "T-1/../../../etc",
      action: "get",
      confidence: "high",
      ambiguityReason: null,
    };
    const result = await runOperation("task.get", classification, BUDGET, {
      cwd: root,
    });
    assert.equal(result.ok, false);
    assert.deepEqual(result.records, []);
  }));

// ---------------------------------------------------------------- budget boundaries

test("exact-limit success: a task exactly at budget.maxBytes is returned", () =>
  withFixture(async (root) => {
    const file = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-1",
      "task.md",
    );
    const size = (await stat(file)).size;
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      { ...BUDGET, maxBytes: size },
      { cwd: root },
    );
    assert.equal(result.ok, true, result.reason);
  }));

test("one-over-limit failure: a task one byte over budget.maxBytes is refused, not truncated", () =>
  withFixture(async (root) => {
    const file = path.join(
      root,
      "projects",
      "atlas",
      "tasks",
      "T-1",
      "task.md",
    );
    const size = (await stat(file)).size;
    const result = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      { ...BUDGET, maxBytes: size - 1 },
      { cwd: root },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /refusing to silently truncate/);
    assert.deepEqual(result.records, []);
  }));

test("oversized content is refused for a write rather than clipped", () =>
  withFixture(async (root) => {
    const target = path.join(root, "personal", "memory", "big.md");
    const result = await runOperation(
      "memory.write",
      classifyIntent("remember this"),
      { ...BUDGET, maxBytes: 100 },
      {
        cwd: root,
        slug: "big",
        content: "x".repeat(500),
        approval: approval("memory.write", target),
      },
    );
    assert.equal(result.ok, false);
    assert.match(result.reason, /maxBytes/);
  }));

test("an oversized query does not produce an unbounded result", () =>
  withFixture(async (root) => {
    const result = await runOperation(
      "memory.search",
      classifyIntent("what do you remember"),
      BUDGET,
      { cwd: root, query: "z".repeat(50_000) },
    );
    assert.equal(result.ok, true);
    assert.equal(result.records.length, 0);
    assert.ok(JSON.stringify(result).length < 2_000);
  }));

// ---------------------------------------------------------------- atomicity & persistence

test("a failed write leaves no partial content and no temp file behind", () =>
  withFixture(async (root) => {
    const directory = path.join(root, "personal", "memory");
    const target = path.join(directory, "locked.md");
    await rm(directory, { recursive: true, force: true });
    await writeFile(directory, "not-a-directory");
    try {
      const result = await runOperation(
        "memory.write",
        classifyIntent("remember this"),
        BUDGET,
        {
          cwd: root,
          slug: "locked",
          content: "should not land",
          approval: approval("memory.write", target),
        },
      );
      assert.equal(result.ok, false);
      assert.match(result.reason, /write failed atomically/);
    } finally {
      await rm(directory, { force: true });
    }
    assert.equal((await stat(path.dirname(directory))).isDirectory(), true);
  }));

test("read operations never write anything to the record directories", () =>
  withFixture(async (root) => {
    const memoryDir = path.join(root, "personal", "memory");
    const before = (await readdir(memoryDir)).sort();
    await runOperation(
      "memory.search",
      classifyIntent("what do you remember"),
      BUDGET,
      {
        cwd: root,
      },
    );
    await runOperation("task.get", classifyIntent("show T-1"), BUDGET, {
      cwd: root,
    });
    const after = (await readdir(memoryDir)).sort();
    assert.deepEqual(before, after);
  }));

// ---------------------------------------------------------------- determinism & parity

test("repeated identical operations return identical results", () =>
  withFixture(async (root) => {
    const first = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    const second = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.deepEqual(first, second);
  }));

test("Arabic and English requests reach the same operation and the same records", () =>
  withFixture(async (root) => {
    const arabic = await runOperation(
      "task.get",
      classifyIntent("عرض T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    const english = await runOperation(
      "task.get",
      classifyIntent("show T-1"),
      BUDGET,
      {
        cwd: root,
      },
    );
    assert.deepEqual(arabic, english);
    assert.equal(
      operationForIntent(classifyIntent("شنو المشروع الحالي")).operation,
      "project.detect",
    );
    assert.equal(
      operationForIntent(classifyIntent("احفظ هذا كقرار")).operation,
      "knowledge.write",
    );
  }));
