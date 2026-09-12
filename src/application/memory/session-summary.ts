import { appendFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { atlasPath } from "../../paths.js";

export async function appendSessionSummary(input: { sessionId: string; provider: string; status: string; exitCode: number; }): Promise<void> {
  const directory = atlasPath("personal", "brain-dump", "sessions");
  await mkdir(directory, { recursive: true });
  const date = new Date().toISOString();
  const summary = `- ${date} | session=${input.sessionId} | provider=${input.provider} | status=${input.status} | exit=${input.exitCode}\n`;
  await appendFile(path.join(directory, `${date.slice(0, 10)}-${input.sessionId}.md`), `# Session ${input.sessionId}\n\n${summary}`);
  await appendFile(atlasPath("personal", "brain-dump", "MEMORY.md"), summary);
}
