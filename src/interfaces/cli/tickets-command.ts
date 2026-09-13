import { archiveDoneTickets } from "../../application/tickets/archive-tickets.js";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export type TicketSummary = { id: string; title: string; state: string; goal: string; updatedAt: string };

export async function listTickets(state?: string): Promise<TicketSummary[]> {
  const root = atlasPath("projects", "atlas", "tickets");
  const records: TicketSummary[] = [];
  let entries;
  try { entries = await readdir(root, { withFileTypes: true }); } catch { return records; }
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.name === "archive") continue;
    const file = path.join(root, entry.name, "task.md");
    let source: string;
    try { source = await readFile(file, "utf8"); } catch { continue; }
    const fields = Object.fromEntries(source.slice(0, source.indexOf("\n---", 4)).split("\n").slice(1)
      .filter((line) => /^[\w-]+:/.test(line)).map((line) => { const index = line.indexOf(":"); return [line.slice(0, index), line.slice(index + 1).trim()]; }));
    if (state && fields.state !== state) continue;
    records.push({ id: fields.id ?? entry.name, title: fields.title ?? "", state: fields.state ?? "", goal: fields.goal ?? "", updatedAt: fields.updated_at ?? "" });
  }
  return records.sort((a, b) => a.id.localeCompare(b.id));
}

export async function runTicketsCommand(action: string, args: string[]): Promise<void> {
  if (action === "list") {
    console.log(JSON.stringify(await listTickets(args[0]), null, 2));
    return;
  }
  if (action !== "archive") {
    console.error("Usage: atlas tickets list [state]|archive [--apply]");
    process.exitCode = 1;
    return;
  }
  const result = await archiveDoneTickets(undefined, args.includes("--apply"));
  console.log(JSON.stringify({ dryRun: !args.includes("--apply"), ...result }, null, 2));
}
