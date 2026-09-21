const commandGroups = [
  [
    "Workspace",
    "setup, context, project, tasks, policy, lifecycle, doctor, repair",
  ],
  ["Execution", "run, session, service, intercept, operate, gateway, schedule"],
  ["Providers", "client, install, update, remove, auth, mcp, browser"],
  [
    "Knowledge",
    "memory, observe, capture, handoff, idea, daily, skill, catalog",
  ],
  ["Integrations", "obsidian, hook, migrate, env"],
] as const;

export function renderHelp(): string {
  const groups = commandGroups
    .map(([label, commands]) => `  ${label.padEnd(12)} ${commands}`)
    .join("\n");
  return `Usage: atlas <command> [options]\n\nCommands:\n${groups}\n\nGlobal options:\n  -h, --help     Show this help\n  -v, --version  Show the installed version`;
}
