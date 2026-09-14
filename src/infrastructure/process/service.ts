import { loadObsidianConnection } from "../../application/obsidian/vault-discovery.js";
import { watchObsidianVault } from "../../application/obsidian/vault-sync.js";

export async function runService(): Promise<void> {
  console.log("Atlas runtime is running.");
  const controller = new AbortController();
  let watcher: Promise<void> | undefined;
  try {
    const connection = await loadObsidianConnection();
    watcher = watchObsidianVault(connection, undefined, controller.signal).catch((error) => {
      console.error(`Obsidian watcher stopped: ${error instanceof Error ? error.message : String(error)}`);
    });
    console.log(`Obsidian watcher enabled: ${connection.vaultPath}`);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") {
      console.error(`Obsidian watcher unavailable: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
  const heartbeat = setInterval(() => undefined, 60_000);
  await new Promise<void>((resolve) => {
    const shutdown = (signal: NodeJS.Signals) => {
      console.log(`Atlas runtime received ${signal}, shutting down.`);
      clearInterval(heartbeat);
      controller.abort();
      process.off("SIGINT", shutdown);
      process.off("SIGTERM", shutdown);
      resolve();
    };
    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
  });
  await watcher;
  console.log("Atlas runtime stopped.");
}
