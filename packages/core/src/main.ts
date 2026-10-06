#!/usr/bin/env node
import { commandRegistry } from "./interfaces/cli/command-registry.js";
import { renderHelp } from "./interfaces/cli/help-command.js";
import { onboard } from "./interfaces/cli/onboard-command.js";
import { oceanVersion } from "./version.js";

const command = process.argv[2] === "--yes" ? undefined : process.argv[2];

if (command === "--version" || command === "-v") {
  console.log(await oceanVersion());
} else if (command === "--help" || command === "-h") {
  console.log(renderHelp());
} else if (!command) {
  await onboard({ yes: process.argv.includes("--yes") });
} else {
  const handler = commandRegistry[command];
  if (handler) {
    await handler();
  } else {
    console.error(`Unknown command: ${command}`);
    process.exitCode = 1;
  }
}
