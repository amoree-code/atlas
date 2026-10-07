import type { Dirent } from "node:fs";
import { mkdir, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { atomicWrite } from "../../fs-utils.js";
import { PROJECTS_DIR, projectFolder, resolveWithin } from "../../paths.js";
import type { ContextBudget } from "../context/context-ladder.js";
import type { IntentClassification } from "../context/intent-router.js";
import { completeTask } from "../tasks/archive-tasks.js";
import {
  approvalMatchesTarget,
  type OperationRecord,
  type OperationResult,
  operationResult,
  selectFields,
  shapeRecords,
  validateTaskIdentifier,
  validateWriteTarget,
  type WriteApproval,
} from "./operation-contract.js";
import {
  crossProjectGuard,
  type OperationOptions,
  taskRoot,
} from "./operation-scope.js";
import {
  FRONTMATTER_READ_BYTES,
  freshnessFor,
  readFrontmatterFile,
  relativeToOcean,
  requireAbsentTarget,
} from "./record-io.js";

const TASK_FIELDS = ["id", "title", "state", "goal", "priority", "updated_at"];
const TASK_ID_LIST_SHAPE = /^T-\d+$/;
const MUTABLE_TASK_FIELDS = [
  "state",
  "goal",
  "priority",
  "updated_at",
  "next_action",
];

export async function taskGet(
  classification: IntentClassification,
  budget: ContextBudget,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const identifier = validateTaskIdentifier(classification.identifier);
  if (!identifier.valid) return operationResult("task.get", identifier.reason);
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("task.get", project.reason);

  let file: string;
  try {
    file = resolveWithin(
      taskRoot(project.projectId),
      identifier.value,
      "task.md",
    );
  } catch {
    return operationResult(
      "task.get",
      "resolved task path escapes the project task root",
    );
  }

  const record = await readFrontmatterFile(file);
  if (!record)
    return operationResult(
      "task.get",
      `task ${identifier.value} was not found in project '${project.projectId}'`,
    );
  if (record.size > budget.maxBytes) {
    return operationResult(
      "task.get",
      `task ${identifier.value} is ${record.size} bytes, budget.maxBytes allows ${budget.maxBytes} — refusing to silently truncate`,
      { violations: ["max-bytes-exceeded"] },
    );
  }
  const shaped: OperationRecord = {
    identifier: identifier.value,
    recordType: "task",
    provenance: "task",
    sourcePath: relativeToOcean(file),
    freshness: freshnessFor(record.mtimeMs),
    confidence: classification.confidence,
    selectionReason: `exact task record requested by identifier ${identifier.value}`,
    fields: selectFields(record.fields, TASK_FIELDS),
  };
  return {
    operation: "task.get",
    ok: true,
    reason: `task ${identifier.value} selected`,
    records: [shaped],
    violations: [],
    written: null,
    packet: null,
  };
}

export async function taskList(
  classification: IntentClassification,
  budget: ContextBudget,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("task.list", project.reason);

  const root = taskRoot(project.projectId);
  let entries: Dirent[];
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return operationResult(
      "task.list",
      `no task directory for project '${project.projectId}'`,
    );
  }

  const records: OperationRecord[] = [];
  const violations: string[] = [];
  let bytes = 0;
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    if (!TASK_ID_LIST_SHAPE.test(entry.name)) continue;
    const file = path.join(root, entry.name, "task.md");
    const record = await readFrontmatterFile(file);
    if (!record) continue;
    bytes += Math.min(record.size, FRONTMATTER_READ_BYTES);
    if (bytes > budget.maxBytes) {
      violations.push(
        `max-bytes-exceeded: stopped listing at ${bytes} bytes (budget ${budget.maxBytes})`,
      );
      break;
    }
    records.push({
      identifier: record.fields.id ?? entry.name,
      recordType: "task",
      provenance: "task",
      sourcePath: relativeToOcean(file),
      freshness: freshnessFor(record.mtimeMs),
      confidence: classification.confidence,
      selectionReason: `live task in project '${project.projectId}'`,
      fields: selectFields(record.fields, TASK_FIELDS),
    });
  }
  const shaped = shapeRecords(records, budget.maxFiles);
  return {
    operation: "task.list",
    ok: true,
    reason: `${shaped.records.length} task(s) listed for project '${project.projectId}'`,
    records: shaped.records,
    violations: [...violations, ...shaped.violations],
    written: null,
    packet: null,
  };
}

async function nextTaskId(root: string): Promise<string> {
  const ids: number[] = [];
  const collect = async (directory: string): Promise<void> => {
    let entries: Dirent[];
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const match = TASK_ID_LIST_SHAPE.exec(entry.name);
      if (match) ids.push(Number(entry.name.slice(2)));
      if (entry.name === "archive")
        await collect(path.join(directory, entry.name));
    }
  };
  await collect(root);
  return `T-${(ids.length ? Math.max(...ids) : 0) + 1}`;
}

export async function taskCreate(
  classification: IntentClassification,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("task.create", project.reason);
  const title = classification.identifier?.trim();
  if (!title || title.length > 200 || /[\r\n]/.test(title))
    return operationResult(
      "task.create",
      "write refused: an explicit single-line task title is required",
    );
  const root = taskRoot(project.projectId);
  const id = await nextTaskId(root);
  const target = validateWriteTarget(
    PROJECTS_DIR,
    projectFolder(project.projectId),
    "tasks",
    id,
    "task.md",
  );
  if (!target.valid) return operationResult("task.create", target.reason);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult("task.create", approvalCheck.reason);
  const absent = await requireAbsentTarget(target.value);
  if (!absent.ok) return operationResult("task.create", absent.reason);
  const today = new Date().toISOString().slice(0, 10);
  const objective = (options.content ?? title).trim().replace(/[\r\n]+/g, " ");
  const source = `---\nid: ${id}\ntitle: ${title}\nstate: active\nproject: ${project.projectId}\nopened: ${today}\nupdated: ${today}\nartifacts: []\nclass: medium\nexpected_context: medium\n---\n\n## Objective\n\n${objective}\n\n## Definition of done\n\nThe requested outcome is implemented and its verification passes.\n\n## Next action\n\nInspect the project and define the first implementation slice.\n\n## Verification\n\nPending.\n\n## Blockers\n\nNone.\n\n## Log\n\n- ${today} — Task created.\n`;
  try {
    await mkdir(path.dirname(target.value), { recursive: true });
    const bytes = await atomicWrite(target.value, source);
    return {
      operation: "task.create",
      ok: true,
      reason: `${id} created for project '${project.projectId}'`,
      records: [],
      violations: [],
      written: { sourcePath: relativeToOcean(target.value), bytes },
      packet: null,
    };
  } catch (error) {
    return operationResult(
      "task.create",
      `task creation failed atomically, no partial content left: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

export async function taskUpdate(
  classification: IntentClassification,
  budget: ContextBudget,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const identifier = validateTaskIdentifier(classification.identifier);
  if (!identifier.valid)
    return operationResult("task.update", identifier.reason);
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("task.update", project.reason);
  const patch = options.patch ?? {};
  const patchKeys = Object.keys(patch);
  if (patchKeys.length === 0)
    return operationResult(
      "task.update",
      "write refused: no explicit field patch supplied",
    );
  const unknownField = patchKeys.find(
    (key) => !MUTABLE_TASK_FIELDS.includes(key),
  );
  if (unknownField)
    return operationResult(
      "task.update",
      `write refused: field '${unknownField}' is not an updatable task field`,
    );

  const target = validateWriteTarget(
    PROJECTS_DIR,
    projectFolder(project.projectId),
    "tasks",
    identifier.value,
    "task.md",
  );
  if (!target.valid) return operationResult("task.update", target.reason);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult("task.update", approvalCheck.reason);

  let source: string;
  try {
    source = await readFile(target.value, "utf8");
  } catch {
    return operationResult(
      "task.update",
      `task ${identifier.value} was not found in project '${project.projectId}'`,
    );
  }
  if (Buffer.byteLength(source, "utf8") > budget.maxBytes) {
    return operationResult(
      "task.update",
      `task ${identifier.value} exceeds budget.maxBytes (${budget.maxBytes}) — refusing to rewrite a record it cannot fully read`,
      { violations: ["max-bytes-exceeded"] },
    );
  }

  let updated = source;
  for (const [key, value] of Object.entries(patch)) {
    if (value.includes("\n"))
      return operationResult(
        "task.update",
        `write refused: value for '${key}' must be a single line`,
      );
    const pattern = new RegExp(`^${key}:.*$`, "m");
    updated = pattern.test(updated)
      ? updated.replace(pattern, `${key}: ${value}`)
      : updated;
  }
  if (updated === source)
    return operationResult(
      "task.update",
      "write refused: patch did not match any existing frontmatter field",
    );

  const bytes = await atomicWrite(target.value, updated);
  return {
    operation: "task.update",
    ok: true,
    reason: `task ${identifier.value} updated (${patchKeys.join(", ")})`,
    records: [],
    violations: [],
    written: { sourcePath: relativeToOcean(target.value), bytes },
    packet: null,
  };
}

export async function taskCompleteOperation(
  classification: IntentClassification,
  _budget: ContextBudget,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const identifier = validateTaskIdentifier(classification.identifier);
  if (!identifier.valid)
    return operationResult("task.complete", identifier.reason);
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("task.complete", project.reason);

  const target = validateWriteTarget(
    PROJECTS_DIR,
    projectFolder(project.projectId),
    "tasks",
    identifier.value,
    "task.md",
  );
  if (!target.valid) return operationResult("task.complete", target.reason);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult("task.complete", approvalCheck.reason);

  try {
    // Reuses the existing governed completion path: it refuses a task with unchecked work.
    const result = await completeTask(
      identifier.value,
      taskRoot(project.projectId),
    );
    return {
      operation: "task.complete",
      ok: true,
      reason: `task ${identifier.value} completed (state: ${result.state})`,
      records: [],
      violations: [],
      written: { sourcePath: relativeToOcean(target.value), bytes: 0 },
      packet: null,
    };
  } catch (error) {
    return operationResult(
      "task.complete",
      error instanceof Error ? error.message : String(error),
    );
  }
}
