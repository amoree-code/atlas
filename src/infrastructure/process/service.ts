export async function runService(): Promise<void> {
  console.log("Atlas runtime is running.");
  const heartbeat = setInterval(() => undefined, 60_000);
  await new Promise<void>((resolve) => {
    const shutdown = (signal: NodeJS.Signals) => {
      console.log(`Atlas runtime received ${signal}, shutting down.`);
      clearInterval(heartbeat);
      process.off("SIGINT", shutdown);
      process.off("SIGTERM", shutdown);
      resolve();
    };
    process.on("SIGINT", shutdown);
    process.on("SIGTERM", shutdown);
  });
  console.log("Atlas runtime stopped.");
}
