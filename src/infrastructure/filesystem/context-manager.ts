import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Profile } from "../../domain/profiles/profile.js";
import type { ContextManifest } from "../../domain/context/context.js";
import { validateContextManifest } from "../../domain/context/context-validator.js";

export type { ContextManifest } from "../../domain/context/context.js";

export type BuiltContext = { manifest: ContextManifest; content: string };

export async function buildContext(profile: Profile, root: string, maxBytes = 32_000): Promise<BuiltContext> {
  const chunks: string[] = [];
  const files: string[] = [];
  let bytes = 0;

  for (const relativePath of profile.contextSources) {
    if (bytes >= maxBytes) break;
    const absolutePath = path.resolve(root, relativePath);
    const allowed = profile.allowedPaths.some((allowedPath) => {
      const boundary = path.resolve(root, allowedPath);
      return absolutePath === boundary || absolutePath.startsWith(`${boundary}${path.sep}`);
    });
    if (!allowed) continue;

    const content = (await readFile(absolutePath, "utf8")).slice(0, maxBytes - bytes);
    chunks.push(`## ${relativePath}\n${content}`);
    files.push(relativePath);
    bytes += Buffer.byteLength(content);
  }

  return {
    content: chunks.join("\n\n"),
    manifest: validateContextManifest({
      files,
      bytes,
      compactedSummary: null,
      lastContextCheckpoint: new Date().toISOString(),
    }),
  };
}
