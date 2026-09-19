import { readFile } from "node:fs/promises";
import { resolveProject } from "../../application/context/project-resolution.js";
import { enginePath } from "../../paths.js";
import { listTickets } from "./tickets-command.js";

export async function runContextCommand(json = false): Promise<void> {
  const version = (await readFile(enginePath("VERSION"), "utf8")).trim();
  const resolution = await resolveProject(process.cwd());
  const project = resolution.status === "bound" ? resolution.projectId : null;
  const tickets = project
    ? (await listTickets(undefined, project)).filter(
        (ticket) => ticket.state === "active" || ticket.state === "blocked",
      )
    : [];
  const context = {
    project,
    projectResolution: resolution,
    version,
    roots: ["personal", "projects", "system"],
    tickets,
  };
  if (json) {
    console.log(JSON.stringify(context, null, 2));
    return;
  }
  console.log(
    `Atlas context\nversion: ${version}\nroots: personal, projects, system`,
  );
  if (resolution.status !== "bound")
    console.log(
      `project: ${resolution.status} — no Atlas binding for this directory; run 'atlas project bind <name> <path>'`,
    );
  else
    console.log(
      `project: ${resolution.projectId} (confidence: ${resolution.confidence})`,
    );
  if (!tickets.length) console.log("active tickets: none");
  else
    for (const ticket of tickets)
      console.log(
        `${ticket.id} [${ticket.state}] ${ticket.title} — ${ticket.goal}`,
      );
}
