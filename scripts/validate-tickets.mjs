#!/usr/bin/env node
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? "../projects/atlas/tickets");
const records = [];
const errors = [];

async function walk(directory, archived = false) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) await walk(target, archived || entry.name === "archive");
    else if (entry.name === "task.md") await readTicket(target, archived);
  }
}
async function readTicket(file, archived) {
  const source = await readFile(file, "utf8");
  if (!source.startsWith("---\n")) return errors.push(`${file}: missing frontmatter`);
  const end = source.indexOf("\n---", 4);
  if (end < 0) return errors.push(`${file}: unterminated frontmatter`);
  const fields = Object.fromEntries(source.slice(4, end).split("\n").filter((line) => /^[\w-]+:/.test(line)).map((line) => {
    const separator = line.indexOf(":"); return [line.slice(0, separator), line.slice(separator + 1).trim()];
  }));
  const id = fields.id?.replace(/^['"]|['"]$/g, "");
  const directory = path.basename(path.dirname(file));
  if (!archived) {
    const required = ["id", "title", "state", "project", "goal"];
    for (const field of required) if (!fields[field]) errors.push(`${file}: missing ${field}`);
    if (id && id !== directory) errors.push(`${file}: id does not match directory`);
    if (fields.state && !["planned", "active", "done", "blocked"].includes(fields.state)) errors.push(`${file}: invalid state`);
    const checklist = source.match(/- \"\[[ x]\] .*\"/g) ?? [];
    if (!checklist.length) errors.push(`${file}: missing checklist`);
    if (fields.state === "done" && checklist.some((line) => line.includes("[ ]"))) errors.push(`${file}: done ticket has unchecked work`);
  }
  records.push({ id, file, archived, fields });
}

await walk(root);
const live = records.filter((record) => !record.archived);
const liveIds = new Set();
for (const record of live) {
  if (liveIds.has(record.id)) errors.push(`duplicate live ticket: ${record.id}`);
  liveIds.add(record.id);
}
const knownIds = new Set(records.map((record) => record.id));
for (const record of records) {
  const refs = [...(record.fields.references?.match(/T-\d+/g) ?? [])];
  for (const ref of refs) if (!knownIds.has(ref)) errors.push(`${record.file}: broken reference ${ref}`);
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(`Validated ${live.length} live and ${records.length - live.length} archived tickets`);
