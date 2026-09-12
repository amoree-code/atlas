import { archiveDoneTickets } from "../../application/tickets/archive-tickets.js";

export async function runTicketsCommand(action: string, args: string[]): Promise<void> {
  if (action !== "archive") {
    console.error("Usage: atlas tickets archive [--apply]");
    process.exitCode = 1;
    return;
  }
  const result = await archiveDoneTickets(undefined, args.includes("--apply"));
  console.log(JSON.stringify({ dryRun: !args.includes("--apply"), ...result }, null, 2));
}
