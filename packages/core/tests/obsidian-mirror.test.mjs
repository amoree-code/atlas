import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { ingestVaultChanges } from "../dist/application/obsidian/vault-ingestion.js";
import { PROJECTS_DIR } from "../dist/paths.js";

async function fixture(projectFolder) {
  const root = await mkdtemp(path.join(os.tmpdir(), "ocean-mirror-root-"));
  const vaultPath = await mkdtemp(
    path.join(os.tmpdir(), "ocean-mirror-vault-"),
  );
  await mkdir(path.join(root, PROJECTS_DIR, projectFolder, "tasks"), {
    recursive: true,
  });
  await writeFile(
    path.join(root, PROJECTS_DIR, projectFolder, "README.md"),
    "ocean side\n",
  );
  await mkdir(path.join(vaultPath, "01-Projects", "Ocean"), {
    recursive: true,
  });
  await mkdir(path.join(vaultPath, "01-Projects", "Atlas"), {
    recursive: true,
  });
  return { root, vaultPath };
}

const sync = (added) => ({ added, changed: [], removed: [] });

test("the vault mirror of the workspace project may be named Ocean or the pre-rename Atlas", async () => {
  for (const projectFolder of ["ocean"]) {
    for (const note of ["01-Projects/Ocean.md", "01-Projects/Atlas.md"]) {
      const { root, vaultPath } = await fixture(projectFolder);
      await writeFile(path.join(vaultPath, note), "vault side\n");
      process.env.OCEAN_ROOT = root;
      try {
        const result = await ingestVaultChanges(
          { enabled: true, mode: "read-only", vaultPath },
          sync([note]),
          undefined,
          {},
        );
        assert.equal(result.conflicts.length, 1, `${projectFolder} ${note}`);
        const record = JSON.parse(await readFile(result.conflicts[0], "utf8"));
        assert.equal(record.oceanContent, "ocean side\n");
        assert.equal(record.vaultContent, "vault side\n");
        assert.ok(!("atlasSha256" in record));
      } finally {
        delete process.env.OCEAN_ROOT;
      }
    }
  }
});

test("a vault holding both the Ocean and the Atlas mirror of the same file logs one conflict, not two", async () => {
  const { root, vaultPath } = await fixture("ocean");
  await writeFile(path.join(vaultPath, "01-Projects/Ocean/plan.md"), "a\n");
  await writeFile(path.join(vaultPath, "01-Projects/Atlas/plan.md"), "b\n");
  await mkdir(path.dirname(path.join(root, PROJECTS_DIR, "ocean", "plan.md")), {
    recursive: true,
  });
  process.env.OCEAN_ROOT = root;
  try {
    const result = await ingestVaultChanges(
      { enabled: true, mode: "read-only", vaultPath },
      sync(["01-Projects/Ocean/plan.md", "01-Projects/Atlas/plan.md"]),
      undefined,
      {},
    );
    assert.equal(result.conflicts.length, 1);
  } finally {
    delete process.env.OCEAN_ROOT;
  }
});
