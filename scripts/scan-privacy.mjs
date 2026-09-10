#!/usr/bin/env node
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(process.argv[2] ?? ".");
const findings = [];
const ignoredDirectories = new Set([".git", "node_modules", "dist"]);
const ignoredFiles = new Set(["LICENSE", "pnpm-lock.yaml"]);
const secretPatterns = [/sk-(?:ant-)?[A-Za-z0-9_-]{20,}/, /(?:AIza|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{12,}/, /-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----/];
const privatePathPattern = /(?:^|[\s'"`])(?:\/Users\/[^\s'"`]+|\/home\/[^\s'"`]+|[A-Za-z]:\\Users\\[^\s'"`]+)/;
const emailPattern = /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/i;

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue;
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) await walk(target);
    else if (!ignoredFiles.has(entry.name)) await scan(target);
  }
}
async function scan(file) {
  const info = await stat(file);
  if (info.size > 1_000_000) return;
  const content = await readFile(file, "utf8").catch(() => null);
  if (content === null || content.includes("\u0000")) return;
  const relative = path.relative(root, file);
  if (secretPatterns.some((pattern) => pattern.test(content))) findings.push({ type: "credential", path: relative });
  if (privatePathPattern.test(content)) findings.push({ type: "private-path", path: relative });
  if (emailPattern.test(content) && !relative.endsWith(".md")) findings.push({ type: "personal-data", path: relative });
}
await walk(root);
if (findings.length) {
  console.error(JSON.stringify({ ok: false, findings }, null, 2));
  process.exit(1);
}
console.log(JSON.stringify({ ok: true, scannedRoot: root }));
