#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";

if (existsSync(".git")) {
  const result = spawnSync("lefthook", ["install"], {
    stdio: "inherit",
    shell: true,
  });
  process.exit(result.status ?? 0);
}
