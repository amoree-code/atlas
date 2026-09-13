import { doctorMemoryIndexes, syncMemoryIndexes } from "../../application/memory/index-sync.js";

export async function runMemoryCommand(action: string, args: string[]): Promise<void> {
  if (action === "doctor") {
    const result = await doctorMemoryIndexes();
    if (!result.ok) {
      if (result.missing.length) console.error(`NOT READY: unindexed records: ${result.missing.join(", ")}`);
      if (result.broken.length) console.error(`NOT READY: broken index links: ${result.broken.join(", ")}`);
      process.exitCode = 1;
    } else console.log("PROVEN: memory and knowledge indexes are synchronized.");
    return;
  }
  if (action === "sync") {
    const result = await syncMemoryIndexes(args.includes("--apply"));
    console.log(JSON.stringify({ dryRun: !args.includes("--apply"), stores: result }, null, 2));
    return;
  }
  console.error("Usage: atlas memory doctor|sync [--apply]");
  process.exitCode = 1;
}
