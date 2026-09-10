import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(new URL("..", import.meta.url).pathname);
const packageJson = JSON.parse(await readFile(path.join(root, "package.json"), "utf8"));
const version = (await readFile(path.join(root, "VERSION"), "utf8")).trim();
const changelog = await readFile(path.join(root, "CHANGELOG.md"), "utf8");
const readme = await readFile(path.join(root, "README.md"), "utf8");
const findings = [];

if (packageJson.version !== version) findings.push(`version mismatch: package.json=${packageJson.version}, VERSION=${version}`);
if (!changelog.includes(`## ${version}`)) findings.push(`CHANGELOG.md is missing ## ${version}`);
if (!readme.includes("CHANGELOG.md")) findings.push("README.md does not link CHANGELOG.md");
if (JSON.stringify(packageJson.files) !== JSON.stringify(["dist", "templates", "skills"])) findings.push("package files allowlist changed");

async function walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const relative = path.relative(root, path.join(directory, entry.name));
    if (entry.isDirectory()) await walk(path.join(directory, entry.name));
    if (/(?:^|[/\\])runtime(?:[/\\]|$)|(?:^|[/\\])node_modules(?:[/\\]|$)|\/Users\/|\/home\//.test(relative)) {
      findings.push(`disallowed package path: ${relative}`);
    }
  }
}

for (const directory of ["dist", "templates", "skills"]) await walk(path.join(root, directory));
if (findings.length) {
  console.error(findings.join("\n"));
  process.exitCode = 1;
} else {
  console.log(`Package boundary valid for Atlas ${version}`);
}
