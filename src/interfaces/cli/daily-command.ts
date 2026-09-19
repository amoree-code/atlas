import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import type { Session } from "../../domain/sessions/session.js";
import { openSessionStore } from "../../infrastructure/persistence/session-store.js";
import { atlasPath } from "../../paths.js";
import { listTickets } from "./tickets-command.js";

export async function runDailyCommand(
  action: string,
  args: string[],
): Promise<void> {
  if (action !== "start") {
    console.error(
      "Usage: atlas daily start [--apply] [--news <bounded-news-summary>]",
    );
    process.exitCode = 1;
    return;
  }
  const apply = args.includes("--apply");
  const newsIndex = args.indexOf("--news");
  const news =
    newsIndex >= 0
      ? args
          .slice(newsIndex + 1)
          .join(" ")
          .slice(0, 4_000)
      : "";
  const tickets = await listTickets();
  const store = await openSessionStore();
  let sessions: Array<
    Pick<Session, "sessionId" | "title" | "provider" | "status" | "nextAction">
  >;
  try {
    sessions = store
      .list()
      .slice(0, 5)
      .map((session) => ({
        sessionId: session.sessionId,
        title: session.title,
        provider: session.provider,
        status: session.status,
        nextAction: session.nextAction,
      }));
  } finally {
    store.close();
  }
  const date = new Date().toISOString().slice(0, 10);
  const file = atlasPath("personal", "daily", `${date}.md`);
  const content = `${[
    `# Daily brief — ${date}`,
    "",
    "## Brief",
    "",
    tickets.length
      ? tickets
          .map((ticket) => `- ${ticket.id}: ${ticket.title} — ${ticket.goal}`)
          .join("\n")
      : "- No active tickets.",
    "",
    "## Check-in",
    "",
    sessions.length
      ? sessions
          .map(
            (session) =>
              `- ${session.sessionId}: ${session.title || session.provider} — ${session.status}${session.nextAction ? `; next: ${session.nextAction}` : ""}`,
          )
          .join("\n")
      : "- No recent sessions.",
    "",
    "## News",
    "",
    news ||
      "- No news supplied. The active AI client may research only the requested topics and pass a bounded summary with `--news`.",
  ]
    .join("\n")
    .slice(0, 12_000)}\n`;
  if (apply) {
    await mkdir(path.dirname(file), { recursive: true });
    const existing = await readFile(file, "utf8").catch(() => "");
    if (existing.trim())
      throw new Error(`Daily file already has content: ${file}`);
    await writeFile(file, content, "utf8");
  }
  console.log(
    JSON.stringify(
      {
        apply,
        date,
        file,
        bytes: Buffer.byteLength(content),
        tickets: tickets.length,
        sessions: sessions.length,
        news: Boolean(news),
        content,
      },
      null,
      2,
    ),
  );
}
