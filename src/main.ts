import { setup } from "./interfaces/cli/setup-command.js";
import { runAgent } from "./application/runs/run-agent.js";
import { resumeAgent } from "./application/runs/run-agent.js";
import { runService } from "./infrastructure/process/service.js";
import { atlasRoot } from "./paths.js";
import { openSessionStore } from "./infrastructure/persistence/session-store.js";
import { intercept } from "./interfaces/cli/intercept-command.js";
import { loadProviderRegistry } from "./infrastructure/providers/provider-registry.js";
import { installShellPath, registerProvider, syncProviderWrappers, wrapperDoctor } from "./infrastructure/wrappers/wrapper-manager.js";
import { findInstallSpec, installPlan, installProvider, listInstallSpecs, removeInstalledProvider, updateProvider } from "./application/install/provider-installer.js";
import { runAuthCommand } from "./interfaces/cli/auth-command.js";
import { runTicketsCommand } from "./interfaces/cli/tickets-command.js";

const command = process.argv[2] ?? "service";

if (command === "setup") {
  await setup();
} else if (command === "service") {
  await runService();
} else if (command === "intercept") {
  const clientIndex = process.argv.indexOf("--client");
  const separatorIndex = process.argv.indexOf("--");
  const client = clientIndex >= 0 ? process.argv[clientIndex + 1] : "";
  const args = separatorIndex >= 0 ? process.argv.slice(separatorIndex + 1) : [];
  if (!client) {
    console.error("Usage: atlas intercept --client <provider> -- [args]");
    process.exitCode = 1;
  } else {
    process.exitCode = await intercept(client, args);
  }
} else if (command === "client") {
  const action = process.argv[3] ?? "list";
  if (action === "list") {
    console.log(JSON.stringify(loadProviderRegistry(), null, 2));
  } else if (action === "sync") {
    const result = await syncProviderWrappers();
    console.log(JSON.stringify({ directory: result.directory, providers: result.providers }, null, 2));
  } else if (action === "register") {
    const id = process.argv[4];
    const provider = await registerProvider(id ?? "", process.argv[5] ?? id ?? "");
    console.log(JSON.stringify(provider, null, 2));
  } else if (action === "doctor") {
    const findings = await wrapperDoctor();
    if (findings.length) {
      findings.forEach((finding) => console.error(`NOT READY: ${finding}`));
      process.exitCode = 1;
    } else {
      console.log("PROVEN: Atlas wrappers are configured and provider binaries resolve outside the shim directory.");
    }
  } else {
    console.error("Usage: atlas client list|sync|register <id> [command]|doctor");
    process.exitCode = 1;
  }
} else if (command === "install") {
  const id = process.argv[3];
  if (!id) {
    console.error("Usage: atlas install <client> [--yes]");
    process.exitCode = 1;
  } else {
    try {
      const spec = findInstallSpec(id);
      if (!process.argv.includes("--yes")) {
        console.log(JSON.stringify({ approvalRequired: true, plan: installPlan(spec.provider.id) }, null, 2));
        process.exitCode = 2;
      } else {
        const result = await installProvider(spec.provider.id, true);
        console.log(JSON.stringify({ installed: true, provider: result.provider, executable: result.executable }, null, 2));
      }
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
} else if (command === "auth") {
  await runAuthCommand(process.argv[3] ?? "", process.argv[4] ?? "");
} else if (command === "tickets") {
  await runTicketsCommand(process.argv[3] ?? "", process.argv.slice(4));
} else if (command === "catalog") {
  console.log(JSON.stringify(listInstallSpecs().map((spec) => ({ id: spec.provider.id, command: spec.provider.command, installer: installPlan(spec.provider.id) })), null, 2));
} else if (command === "env") {
  console.log(await installShellPath());
} else if (command === "update" || command === "remove") {
  const id = process.argv[3];
  if (!id || !process.argv.includes("--yes")) {
    console.error(`Usage: atlas ${command} <client> --yes`);
    process.exitCode = 2;
  } else {
    try {
      const result = command === "update"
        ? await updateProvider(id, true)
        : await removeInstalledProvider(id, true);
      console.log(JSON.stringify({ [command === "update" ? "updated" : "removed"]: true, provider: result }, null, 2));
    } catch (error) {
      console.error(error instanceof Error ? error.message : String(error));
      process.exitCode = 1;
    }
  }
} else if (command === "doctor") {
  const pathIndex = process.argv.indexOf("--path");
  const findings = await wrapperDoctor(pathIndex >= 0 ? process.argv[pathIndex + 1] : undefined);
  if (findings.length) {
    findings.forEach((finding) => console.error(`NOT READY: ${finding}`));
    process.exitCode = 1;
  } else {
    console.log("PROVEN: Atlas wrappers are configured and provider binaries resolve outside the shim directory.");
  }
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
