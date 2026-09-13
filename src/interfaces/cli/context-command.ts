import { readFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";
import { listTickets } from "./tickets-command.js";

export async function runContextCommand(json = false): Promise<void> {
  const version = (await readFile(path.join(atlasPath("engine"), "VERSION"), "utf8")).trim();
  const tickets = (await listTickets()).filter((ticket) => ticket.state === "active" || ticket.state === "blocked");
  const context = { project: "atlas", version, roots: ["personal", "projects", "system"], tickets };
  if (json) {
    console.log(JSON.stringify(context, null, 2));
    return;
  }
  console.log(`Atlas context\nversion: ${version}\nroots: personal, projects, system`);
  if (!tickets.length) console.log("active tickets: none");
  else for (const ticket of tickets) console.log(`${ticket.id} [${ticket.state}] ${ticket.title} — ${ticket.goal}`);
}
