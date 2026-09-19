#!/usr/bin/env node
import { access, readdir, readFile } from "node:fs/promises";
import path from "node:path";

const explicitRoot = process.argv[2];
const root = path.resolve(explicitRoot ?? "../projects/atlas/tickets");
const records = [];
const errors = [];

try {
  await access(root);
} catch (error) {
  if (!explicitRoot && error.code === "ENOENT") {
    console.log("No private ticket workspace found; skipped ticket validation");
    process.exit(0);
  }
  throw error;
}

async function walk(directory, archived = false) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory())
      await walk(target, archived || entry.name === "archive");
    else if (entry.name === "task.md") await readTicket(target, archived);
  }
}
async function readTicket(file, archived) {
  const source = await readFile(file, "utf8");
  if (!source.startsWith("---\n"))
    return errors.push(`${file}: missing frontmatter`);
  const end = source.indexOf("\n---", 4);
  if (end < 0) return errors.push(`${file}: unterminated frontmatter`);
  const fields = Object.fromEntries(
    source
      .slice(4, end)
      .split("\n")
      .filter((line) => /^[\w-]+:/.test(line))
      .map((line) => {
        const separator = line.indexOf(":");
        return [line.slice(0, separator), line.slice(separator + 1).trim()];
      }),
  );
  const id = fields.id?.replace(/^['"]|['"]$/g, "");
  const directory = path.basename(path.dirname(file));
  if (!archived) {
    const legacy = Boolean(
      fields.goal || fields.opened_at || fields.updated_at,
    );
    const required = legacy
      ? ["id", "title", "state", "project", "goal"]
      : ["id", "title", "state", "project", "opened", "updated", "artifacts"];
    for (const field of required)
      if (!fields[field]) errors.push(`${file}: missing ${field}`);
    if (id && id !== directory)
      errors.push(`${file}: id does not match directory`);
    if (
      fields.state &&
      !["todo", "active", "paused", "blocked", "done", "cancelled"].includes(
        fields.state,
      )
    )
      errors.push(`${file}: invalid state`);
    if (legacy) {
      const checklist = source.match(/- "\[[ x]\] .*"/g) ?? [];
      if (!checklist.length) errors.push(`${file}: missing checklist`);
      if (
        fields.state === "done" &&
        checklist.some((line) => line.includes("[ ]"))
      )
        errors.push(`${file}: done ticket has unchecked work`);
    } else {
      for (const heading of [
        "Objective",
        "Definition of done",
        "Next action",
        "Verification",
        "Blockers",
        "Log",
      ])
        if (!source.includes(`\n## ${heading}\n`))
          errors.push(`${file}: missing ${heading} section`);
    }
  }
  records.push({ id, file, archived, fields });
}

await walk(root);
const live = records.filter((record) => !record.archived);
const liveIds = new Set();
for (const record of live) {
  if (liveIds.has(record.id))
    errors.push(`duplicate live ticket: ${record.id}`);
  liveIds.add(record.id);
}
const knownIds = new Set(records.map((record) => record.id));
if (knownIds.size !== records.length) {
  const counts = new Map();
  for (const record of records)
    counts.set(record.id, (counts.get(record.id) ?? 0) + 1);
  for (const [id, count] of counts)
    if (count > 1)
      errors.push(`duplicate ticket id across live/archive records: ${id}`);
}
for (const record of records) {
  const refs = [...(record.fields.references?.match(/T-\d+/g) ?? [])];
  for (const ref of refs)
    if (!knownIds.has(ref))
      errors.push(`${record.file}: broken reference ${ref}`);
}
if (errors.length) {
  console.error(errors.join("\n"));
  process.exit(1);
}
console.log(
  `Validated ${live.length} live and ${records.length - live.length} archived tickets`,
);
