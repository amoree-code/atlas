import { doctorMemoryIndexes, syncMemoryIndexes } from "../../application/memory/index-sync.js";
import { deleteProfileFact, readProfileFacts, writeProfileFact } from "../../application/memory/profile-facts.js";

export async function runMemoryCommand(action: string, args: string[]): Promise<void> {
  if (action === "facts") {
    const profile = args[0];
    if (!profile) { console.error("Usage: atlas memory facts <profile> [key] [value]"); process.exitCode = 1; return; }
    if (args[1] === "delete" && args[2]) console.log(JSON.stringify({ deleted: await deleteProfileFact(profile, args[2]) }, null, 2));
    else if (args.length >= 3) console.log(JSON.stringify(await writeProfileFact(profile, args[1], args.slice(2).join(" ")), null, 2));
    else console.log(JSON.stringify(await readProfileFacts(profile), null, 2));
    return;
  }
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
  console.error("Usage: atlas memory doctor|sync [--apply]|facts <profile> [key] [value]|facts <profile> delete <key>");
  process.exitCode = 1;
}
