import { mkdir } from "node:fs/promises";
import path from "node:path";
import { atomicWrite } from "../../fs-utils.js";
import { atlasRoot, resolveWithin } from "../../paths.js";
import type { ContextBudget } from "../context/context-ladder.js";
import type { RecordType } from "../context/context-packet.js";
import type { IntentClassification } from "../context/intent-router.js";
import {
  approvalMatchesTarget,
  type OperationRecord,
  type OperationResult,
  operationResult,
  selectFields,
  shapeRecords,
  validateSlug,
  validateWriteTarget,
  type WriteApproval,
} from "./operation-contract.js";
import type { OperationOptions } from "./operation-scope.js";
import {
  FRONTMATTER_READ_BYTES,
  freshnessFor,
  listRecordFiles,
  readFrontmatterFile,
  relativeToAtlas,
  requireAbsentTarget,
} from "./record-io.js";

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

export async function searchRecords(
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

export async function writeRecord(
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
