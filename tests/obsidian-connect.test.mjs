import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { connectObsidianVault } from "../dist/application/obsidian/vault-discovery.js";

test("connects an Obsidian vault with read-only default", async () => {
  const vaultPath = await mkdtemp(path.join(os.tmpdir(), "atlas-obsidian-connect-"));
  const atlasRoot = await mkdtemp(path.join(os.tmpdir(), "atlas-obsidian-connect-state-"));
  const configFile = path.join(atlasRoot, "system", "integrations", "obsidian", "connection.json");
  await mkdir(path.join(vaultPath, ".obsidian"));

  const result = await connectObsidianVault(vaultPath, "read-only", configFile);
  const connection = JSON.parse(await readFile(configFile, "utf8"));
  assert.equal(result.vaultPath, vaultPath);
  assert.deepEqual(connection, { enabled: true, mode: "read-only", vaultPath });
});
