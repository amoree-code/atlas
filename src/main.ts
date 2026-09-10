import { setup } from "./interfaces/cli/setup-command.js";
import { runAgent } from "./application/runs/run-agent.js";
import { resumeAgent } from "./application/runs/run-agent.js";
import { runService } from "./infrastructure/process/service.js";
import { atlasRoot } from "./paths.js";
import { openSessionStore } from "./infrastructure/persistence/session-store.js";

const command = process.argv[2] ?? "service";

if (command === "setup") {
  await setup();
} else if (command === "service") {
  await runService();
} else if (command === "run") {
  const profileIndex = process.argv.indexOf("--profile");
  const promptIndex = process.argv.indexOf("--prompt");
  const profileName = profileIndex >= 0 ? process.argv[profileIndex + 1] : "default";
  const prompt = promptIndex >= 0 ? process.argv.slice(promptIndex + 1).join(" ") : "";
  if (!profileName || !prompt) {
    console.error("Usage: atlas run --profile <name> --prompt <text>");
    process.exitCode = 1;
  } else {
    const session = await runAgent({ profileName, prompt, cwd: atlasRoot() });
    console.log(JSON.stringify({ sessionId: session.sessionId, status: session.status }));
  }
} else if (command === "session") {
  const action = process.argv[3] ?? "list";
  const store = await openSessionStore();
  if (action === "list") {
    console.log(JSON.stringify(store.list()));
    store.close();
  } else if (action === "show") {
    const session = store.get(process.argv[4] ?? "");
    store.close();
    if (!session) { console.error("Session not found"); process.exitCode = 1; }
    else console.log(JSON.stringify(session));
  } else if (action === "resume") {
    const sessionId = process.argv[4];
    const prompt = process.argv.slice(5).join(" ");
    store.close();
    if (!sessionId || !prompt) {
      console.error("Usage: atlas session resume <session-id> <prompt>");
      process.exitCode = 1;
    } else {
      const session = await resumeAgent(sessionId, prompt);
      console.log(JSON.stringify({ sessionId: session.sessionId, status: session.status }));
    }
  } else {
    store.close();
    console.error("Usage: atlas session list|show <session-id>|resume <session-id> <prompt>");
    process.exitCode = 1;
  }
} else {
  console.error(`Unknown command: ${command}`);
  process.exitCode = 1;
}
