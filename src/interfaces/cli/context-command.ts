import { resolveProject } from "../../application/context/project-resolution.js";
import { atlasVersion } from "../../version.js";
import { listTasks } from "./tasks-command.js";

export async function runContextCommand(json = false): Promise<void> {
  const version = await atlasVersion();
  const resolution = await resolveProject(process.cwd());
  const project = resolution.status === "bound" ? resolution.projectId : null;
  const tasks = project
    ? (await listTasks(undefined, project)).filter(
        (task) => task.state === "active" || task.state === "blocked",
      )
    : [];
  const context = {
    project,
    projectResolution: resolution,
    version,
    roots: ["personal", "projects", "system"],
    tasks,
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
  if (!tasks.length) console.log("active tasks: none");
  else
    for (const task of tasks)
      console.log(
        `${task.id} [${task.state}] ${task.title} — ${task.goal}`,
      );
}
