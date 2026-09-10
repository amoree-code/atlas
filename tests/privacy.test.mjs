import assert from "node:assert/strict";
import { mkdir, writeFile, mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import test from "node:test";

function scan(root) {
  const child = spawn(process.execPath, [path.join(process.cwd(), "scripts", "scan-privacy.mjs"), root], { stdio: ["ignore", "pipe", "pipe"] });
  return new Promise((resolve) => {
    let stdout = ""; let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}
test("privacy scanner fails without printing secret values", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-privacy-"));
  const secret = ["sk-ant", "test-value-that-must-not-be-printed"].join("-");
  await writeFile(path.join(root, "bad.txt"), secret);
  const result = await scan(root);
  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /credential/);
  assert.doesNotMatch(result.stderr, new RegExp(secret));
});
test("privacy scanner ignores license text and generated directories", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-privacy-clean-"));
  await mkdir(path.join(root, "dist"));
  await writeFile(path.join(root, "LICENSE"), `Copyright 2026 Example <${["legal", "example.com"].join("@")}>`);
  await writeFile(path.join(root, "dist", "bundle.js"), `const token = '${["sk-ant", "generated-value-ignored"].join("-")}';`);
  const result = await scan(root);
  assert.equal(result.code, 0);
});
