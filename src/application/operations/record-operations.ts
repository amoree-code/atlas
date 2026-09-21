import type { Dirent } from "node:fs";
import {
  mkdir,
  readdir,
  readFile,
  rename,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { atlasPath, atlasRoot, resolveWithin } from "../../paths.js";
import type { ContextBudget } from "../context/context-ladder.js";
import type { Freshness, RecordType } from "../context/context-packet.js";
import type { IntentClassification } from "../context/intent-router.js";
import {
  bindProject,
  projectConfirmationQuestion,
  resolveProject,
} from "../context/project-resolution.js";
import { completeTask } from "../tasks/archive-tasks.js";
import {
  approvalMatchesTarget,
  gateOperation,
  type OperationName,
  type OperationRecord,
  type OperationResult,
  operationResult,
  selectFields,
  shapeRecords,
  validateSlug,
  validateTaskIdentifier,
  validateWriteTarget,
  type WriteApproval,
} from "./operation-contract.js";

// Bounded, deterministic Atlas record operations (T-198 slice 7). Every read is scoped to a
// specific record directory and capped by the caller's budget — there is no repository-wide
// scan anywhere in this module. Every write is atomic (temp file + rename) and refuses to
// run without an explicit, matching approval.

const STALE_AFTER_MS = 30 * 24 * 60 * 60 * 1000;
// Hard structural caps, independent of the caller's budget: a directory walk can never
// examine more than this, whatever budget is passed.
const MAX_SCAN_ENTRIES = 200;
const MAX_SCAN_DEPTH = 3;
const FRONTMATTER_READ_BYTES = 4_096;

const KNOWLEDGE_KINDS = [
  "architecture",
  "decisions",
  "discoveries",
  "failures",
  "references",
  "research",
  "results",
  "solutions",
];

function freshnessFor(mtimeMs: number): Freshness {
  return Date.now() - mtimeMs <= STALE_AFTER_MS ? "current" : "stale";
}

function parseFrontmatter(source: string): Record<string, string> {
  if (!source.startsWith("---")) return {};
  const end = source.indexOf("\n---", 3);
  const block = end < 0 ? source.slice(3) : source.slice(3, end);
  const fields: Record<string, string> = {};
  for (const line of block.split("\n")) {
    const match = /^\s{0,2}([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    if (!match) continue;
    if (fields[match[1]] === undefined)
      fields[match[1]] = match[2].trim().replace(/^["']|["']$/g, "");
  }
  return fields;
}

async function readFrontmatterFile(file: string): Promise<{
  fields: Record<string, string>;
  mtimeMs: number;
  size: number;
} | null> {
  try {
    const info = await stat(file);
    if (!info.isFile()) return null;
    const handle = await readFile(file, "utf8");
    return {
      fields: parseFrontmatter(handle.slice(0, FRONTMATTER_READ_BYTES)),
      mtimeMs: info.mtimeMs,
      size: info.size,
    };
  } catch {
    return null;
  }
}

// Depth-limited, entry-capped listing of one record directory. Never recurses outside the
// directory it was given and never returns more than MAX_SCAN_ENTRIES paths.
async function listRecordFiles(
  root: string,
  depth = 0,
  budgetLeft = { entries: MAX_SCAN_ENTRIES },
): Promise<string[]> {
  if (depth > MAX_SCAN_DEPTH || budgetLeft.entries <= 0) return [];
  let entries: Dirent[];
  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch {
    return [];
  }
  const files: string[] = [];
  for (const entry of entries.sort((left, right) =>
    left.name.localeCompare(right.name),
  )) {
    if (budgetLeft.entries <= 0) break;
    if (entry.name.startsWith(".")) continue;
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listRecordFiles(full, depth + 1, budgetLeft)));
      continue;
    }
    if (!entry.name.endsWith(".md")) continue;
    budgetLeft.entries -= 1;
    files.push(full);
  }
  return files;
}

function relativeToAtlas(file: string): string {
  return path.relative(atlasRoot(), file).split(path.sep).join("/");
}

// Atomic write: content lands in a sibling temp file and is renamed into place, so a failure
// never leaves partial content at the destination.
async function atomicWrite(target: string, content: string): Promise<number> {
  const temp = `${target}.atlas-tmp-${process.pid}-${Date.now()}`;
  try {
    await writeFile(temp, content, "utf8");
    await rename(temp, target);
    return Buffer.byteLength(content, "utf8");
  } catch (error) {
    await rm(temp, { force: true });
    throw error;
  }
}

async function requireAbsentTarget(
  target: string,
): Promise<{ ok: true } | { ok: false; reason: string }> {
  try {
    await stat(target);
    return {
      ok: false,
      reason: `refusing to overwrite an existing record at ${relativeToAtlas(target)}`,
    };
  } catch {
    return { ok: true };
  }
}

// --- active project ------------------------------------------------------------------

type ProjectScope =
  | { ok: true; projectId: string }
  | { ok: false; reason: string };

async function activeProjectId(cwd: string): Promise<ProjectScope> {
  const resolution = await resolveProject(cwd);
  if (resolution.status === "bound")
    return { ok: true, projectId: resolution.projectId };
  return {
    ok: false,
    reason: `no bound Atlas project for this working directory (status: ${resolution.status})`,
  };
}

function taskRoot(projectId: string): string {
  return atlasPath("projects", projectId, "tasks");
}

// --- task operations ---------------------------------------------------------------

const TASK_FIELDS = ["id", "title", "state", "goal", "priority", "updated_at"];

export type OperationOptions = {
  cwd?: string;
  approval?: WriteApproval;
  requestedProject?: string;
  patch?: Record<string, string>;
  content?: string;
  slug?: string;
  kind?: string;
  query?: string;
  projectPath?: string;
  provenance?: OperationRecord["provenance"];
  correctionOf?: string;
};

async function crossProjectGuard(
  options: OperationOptions,
  cwd: string,
): Promise<ProjectScope> {
  const active = await activeProjectId(cwd);
  if (!active.ok) return active;
  if (
    options.requestedProject &&
    options.requestedProject !== active.projectId
  ) {
    return {
      ok: false,
      reason: `cross-project request refused: active project is '${active.projectId}', request targeted '${options.requestedProject}'`,
    };
  }
  return active;
}

async function taskGet(
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
    sourcePath: relativeToAtlas(file),
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

async function taskList(
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
      sourcePath: relativeToAtlas(file),
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

const TASK_ID_LIST_SHAPE = /^T-\d+$/;

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

async function taskCreate(
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
    "projects",
    project.projectId,
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
      written: { sourcePath: relativeToAtlas(target.value), bytes },
      packet: null,
    };
  } catch (error) {
    return operationResult(
      "task.create",
      `task creation failed atomically, no partial content left: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

const MUTABLE_TASK_FIELDS = [
  "state",
  "goal",
  "priority",
  "updated_at",
  "next_action",
];

async function taskUpdate(
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
    "projects",
    project.projectId,
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
    written: { sourcePath: relativeToAtlas(target.value), bytes },
    packet: null,
  };
}

async function taskCompleteOperation(
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
    "projects",
    project.projectId,
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
      written: { sourcePath: relativeToAtlas(target.value), bytes: 0 },
      packet: null,
    };
  } catch (error) {
    return operationResult(
      "task.complete",
      error instanceof Error ? error.message : String(error),
    );
  }
}

// --- memory and knowledge -------------------------------------------------------------

const RECORD_FIELDS = [
  "name",
  "description",
  "type",
  "status",
  "confidence",
  "updated",
];

function provenanceFor(
  recordType: RecordType,
  fields: Record<string, string>,
): OperationRecord["provenance"] {
  const declared = (fields.provenance ?? fields.type ?? "").toLowerCase();
  if (
    [
      "fact",
      "preference",
      "decision",
      "lesson",
      "proposal",
      "temporary-note",
    ].includes(declared)
  )
    return declared as OperationRecord["provenance"];
  if (recordType === "task") return "task";
  if (recordType === "project") return "project";
  if (recordType === "execution") return "execution";
  return recordType === "knowledge"
    ? "lesson"
    : recordType === "memory"
      ? "temporary-note"
      : "unknown";
}

function matchesQuery(
  fields: Record<string, string>,
  file: string,
  query: string,
): boolean {
  if (!query) return true;
  const haystack =
    `${path.basename(file)} ${fields.name ?? ""} ${fields.description ?? ""}`.toLowerCase();
  return haystack.includes(query.toLowerCase());
}

async function searchRecords(
  operation: "memory.search" | "knowledge.search",
  recordType: RecordType,
  rootSegments: string[],
  classification: IntentClassification,
  budget: ContextBudget,
  options: OperationOptions,
): Promise<OperationResult> {
  let root: string;
  try {
    root = resolveWithin(atlasRoot(), ...rootSegments);
  } catch {
    return operationResult(operation, "record root escapes the Atlas root");
  }

  const files = await listRecordFiles(root);
  const records: OperationRecord[] = [];
  const violations: string[] = [];
  let bytes = 0;
  for (const file of files) {
    const record = await readFrontmatterFile(file);
    if (!record) continue;
    if (!matchesQuery(record.fields, file, options.query ?? "")) continue;
    bytes += Math.min(record.size, FRONTMATTER_READ_BYTES);
    if (bytes > budget.maxBytes) {
      violations.push(
        `max-bytes-exceeded: stopped searching at ${bytes} bytes (budget ${budget.maxBytes})`,
      );
      break;
    }
    records.push({
      identifier: record.fields.name ?? path.basename(file, ".md"),
      recordType,
      provenance: provenanceFor(recordType, record.fields),
      sourcePath: relativeToAtlas(file),
      freshness: freshnessFor(record.mtimeMs),
      confidence: classification.confidence,
      selectionReason: options.query
        ? `metadata match on query '${options.query}'`
        : `${recordType} record index entry`,
      fields: selectFields(record.fields, RECORD_FIELDS),
    });
  }
  const shaped = shapeRecords(records, budget.maxFiles);
  return {
    operation,
    ok: true,
    reason: `${shaped.records.length} ${recordType} reference(s) selected`,
    records: shaped.records,
    violations: [...violations, ...shaped.violations],
    written: null,
    packet: null,
  };
}

function recordDocument(
  slug: string,
  recordType: string,
  content: string,
  provenance: OperationRecord["provenance"],
  correctionOf?: string,
): string {
  const today = new Date().toISOString().slice(0, 10);
  const correction = correctionOf ? `\n  correction_of: ${correctionOf}` : "";
  return `---\nname: ${slug}\ndescription: ""\nmetadata:\n  type: ${recordType}\n  provenance: ${provenance}\n  status: current\n  created: ${today}\n  updated: ${today}${correction}\n---\n\n${content.trim()}\n`;
}

async function writeRecord(
  operation: "memory.write" | "knowledge.write",
  options: OperationOptions,
  budget: ContextBudget,
): Promise<OperationResult> {
  const slug = validateSlug(options.slug, "record slug");
  if (!slug.valid)
    return operationResult(operation, `write refused: ${slug.reason}`);
  const content = options.content;
  if (typeof content !== "string" || content.trim().length === 0)
    return operationResult(
      operation,
      "write refused: no explicit content supplied",
    );
  if (Buffer.byteLength(content, "utf8") > budget.maxBytes) {
    return operationResult(
      operation,
      `write refused: content is ${Buffer.byteLength(content, "utf8")} bytes, budget.maxBytes allows ${budget.maxBytes}`,
      { violations: ["max-bytes-exceeded"] },
    );
  }
  if (
    options.correctionOf !== undefined &&
    (!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(options.correctionOf) ||
      options.correctionOf.includes(".."))
  ) {
    return operationResult(
      operation,
      "write refused: correctionOf must be an explicit safe record identifier",
    );
  }

  let segments: string[];
  let recordType: string;
  if (operation === "memory.write") {
    segments = ["personal", "memory", `${slug.value}.md`];
    recordType = "memory";
  } else {
    const kind = validateSlug(options.kind, "knowledge kind");
    if (!kind.valid)
      return operationResult(operation, `write refused: ${kind.reason}`);
    if (!KNOWLEDGE_KINDS.includes(kind.value))
      return operationResult(
        operation,
        `write refused: '${kind.value}' is not an allowed knowledge kind`,
      );
    segments = ["personal", "knowledge", kind.value, `${slug.value}.md`];
    recordType = kind.value === "decisions" ? "decision" : "knowledge";
  }

  const target = validateWriteTarget(...segments);
  if (!target.valid)
    return operationResult(operation, `write refused: ${target.reason}`);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult(operation, approvalCheck.reason);
  const absent = await requireAbsentTarget(target.value);
  if (!absent.ok)
    return operationResult(operation, `write refused: ${absent.reason}`);

  try {
    await mkdir(path.dirname(target.value), { recursive: true });
    const provenance =
      options.provenance ??
      (options.correctionOf
        ? "fact"
        : recordType === "memory"
          ? "temporary-note"
          : recordType === "decision"
            ? "decision"
            : "lesson");
    const bytes = await atomicWrite(
      target.value,
      recordDocument(
        slug.value,
        recordType,
        content,
        provenance,
        options.correctionOf,
      ),
    );
    return {
      operation,
      ok: true,
      reason: `${recordType} record '${slug.value}' written`,
      records: [],
      violations: [],
      written: { sourcePath: relativeToAtlas(target.value), bytes },
      packet: null,
    };
  } catch (error) {
    return operationResult(
      operation,
      `write failed atomically, no partial content left: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
}

// --- project operations ---------------------------------------------------------------

async function projectDetect(
  classification: IntentClassification,
  cwd: string,
): Promise<OperationResult> {
  const resolution = await resolveProject(cwd);
  const record: OperationRecord = {
    identifier:
      resolution.status === "bound" ? resolution.projectId : "unbound",
    recordType: "project",
    provenance: "project",
    sourcePath:
      resolution.status === "bound"
        ? relativeToAtlas(atlasPath("projects", resolution.projectId))
        : "",
    freshness: "unknown",
    confidence: classification.confidence,
    selectionReason: `project resolution status '${resolution.status}' for the given working directory`,
    fields: { status: resolution.status, confidence: resolution.confidence },
  };
  return {
    operation: "project.detect",
    ok: true,
    reason: `project resolution: ${resolution.status}`,
    records: [record],
    violations: [],
    written: null,
    packet: null,
    confirmationQuestion: projectConfirmationQuestion(resolution),
  };
}

async function projectCreate(
  classification: IntentClassification,
  options: OperationOptions,
): Promise<OperationResult> {
  const name = validateSlug(classification.identifier, "project name");
  if (!name.valid)
    return operationResult("project.create", `write refused: ${name.reason}`);
  const projectPath = options.projectPath;
  if (typeof projectPath !== "string" || !path.isAbsolute(projectPath)) {
    return operationResult(
      "project.create",
      "write refused: an explicit absolute project path is required",
    );
  }
  if (projectPath.includes("\0"))
    return operationResult(
      "project.create",
      "write refused: project path contains a null byte",
    );

  const target = validateWriteTarget("projects", name.value);
  if (!target.valid)
    return operationResult("project.create", `write refused: ${target.reason}`);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult("project.create", approvalCheck.reason);

  const binding = await bindProject(name.value, projectPath);
  if (binding.conflict) {
    return operationResult(
      "project.create",
      `write refused: '${name.value}' conflicts with an existing binding at ${binding.conflict.path}`,
    );
  }
  await mkdir(target.value, { recursive: true });
  return {
    operation: "project.create",
    ok: true,
    reason: binding.created
      ? `project '${name.value}' created and bound to ${projectPath}`
      : `project '${name.value}' already bound to ${projectPath}`,
    records: [],
    violations: [],
    written: { sourcePath: relativeToAtlas(target.value), bytes: 0 },
    packet: null,
  };
}

async function projectUpdate(
  _classification: IntentClassification,
  options: OperationOptions,
  cwd: string,
): Promise<OperationResult> {
  const project = await crossProjectGuard(options, cwd);
  if (!project.ok) return operationResult("project.update", project.reason);
  const projectPath = options.projectPath;
  if (typeof projectPath !== "string" || !path.isAbsolute(projectPath)) {
    return operationResult(
      "project.update",
      "write refused: an explicit absolute project path is required",
    );
  }
  const target = validateWriteTarget("projects", project.projectId);
  if (!target.valid)
    return operationResult("project.update", `write refused: ${target.reason}`);
  const approvalCheck = approvalMatchesTarget(
    options.approval as WriteApproval,
    target.value,
  );
  if (!approvalCheck.ok)
    return operationResult("project.update", approvalCheck.reason);
  const binding = await bindProject(project.projectId, projectPath);
  if (binding.conflict)
    return operationResult(
      "project.update",
      `write refused: binding conflict for '${project.projectId}'`,
    );
  return {
    operation: "project.update",
    ok: true,
    reason: `project '${project.projectId}' binding confirmed`,
    records: [],
    violations: [],
    written: { sourcePath: relativeToAtlas(target.value), bytes: 0 },
    packet: null,
  };
}

// --- dispatcher --------------------------------------------------------------------

export async function runOperation(
  operation: OperationName,
  classification: IntentClassification,
  budget: unknown,
  options: OperationOptions = {},
): Promise<OperationResult> {
  const gate = gateOperation(
    operation,
    classification,
    budget,
    options.approval,
  );
  if (!gate.ok) return operationResult(operation, gate.reason);
  const bounded = budget as ContextBudget;
  const cwd = options.cwd ?? process.cwd();

  switch (operation) {
    case "task.get":
      return taskGet(classification, bounded, options, cwd);
    case "task.list":
      return taskList(classification, bounded, options, cwd);
    case "task.update":
      return taskUpdate(classification, bounded, options, cwd);
    case "task.complete":
      return taskCompleteOperation(classification, bounded, options, cwd);
    case "task.create":
      return taskCreate(classification, options, cwd);
    case "memory.search":
      return searchRecords(
        "memory.search",
        "memory",
        ["personal", "memory"],
        classification,
        bounded,
        options,
      );
    case "knowledge.search":
      return searchRecords(
        "knowledge.search",
        "knowledge",
        ["personal", "knowledge"],
        classification,
        bounded,
        options,
      );
    case "memory.write":
      return writeRecord("memory.write", options, bounded);
    case "knowledge.write":
      return writeRecord("knowledge.write", options, bounded);
    case "project.detect":
      return projectDetect(classification, cwd);
    case "project.create":
      return projectCreate(classification, options);
    case "project.update":
      return projectUpdate(classification, options, cwd);
    default:
      return operationResult(operation, `unsupported operation '${operation}'`);
  }
}
