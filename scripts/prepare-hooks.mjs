#!/usr/bin/env node
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";

if (existsSync(".git")) {
  const result = spawnSync("lefthook", ["install"], { stdio: "inherit", shell: true });
  process.exit(result.status ?? 0);
}
