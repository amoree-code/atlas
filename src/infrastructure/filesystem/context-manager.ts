import { readFile } from "node:fs/promises";
import path from "node:path";
import type { Profile } from "../../domain/profiles/profile.js";
import type { ContextManifest } from "../../domain/context/context.js";
import { validateContextManifest } from "../../domain/context/context-validator.js";
import { compressContext } from "../../application/context/context-compression.js";

export type { ContextManifest } from "../../domain/context/context.js";

export type BuiltContext = { manifest: ContextManifest; content: string };

export async function buildContext(profile: Profile, root: string, maxBytes = 32_000, options: { compression?: "none" | "atlas-bounded" } = {}): Promise<BuiltContext> {
  const chunks: string[] = [];
  const files: string[] = [];
  const omitted: string[] = [];
  let bytes = 0;
  const sourceBudget = options.compression === "atlas-bounded" ? maxBytes * 4 : maxBytes;

  for (const relativePath of profile.contextSources) {
    if (bytes >= sourceBudget) break;
    const absolutePath = path.resolve(root, relativePath);
    const allowed = profile.allowedPaths.some((allowedPath) => {
      const boundary = path.resolve(root, allowedPath);
      return absolutePath === boundary || absolutePath.startsWith(`${boundary}${path.sep}`);
    });
    if (!allowed) { omitted.push(relativePath); continue; }

    const content = (await readFile(absolutePath, "utf8")).slice(0, sourceBudget - bytes);
    chunks.push(`## ${relativePath}\n${content}`);
    files.push(relativePath);
    bytes += Buffer.byteLength(content);
  }

  const rawContent = chunks.join("\n\n");
  const compression = options.compression === "atlas-bounded" ? compressContext({ sourceId: files.join(",") || "empty-context", content: rawContent, budget: maxBytes }) : null;
  return {
    content: compression?.content ?? rawContent,
    manifest: validateContextManifest({
      files,
      bytes: compression?.compressedBytes ?? bytes,
      compactedSummary: compression?.method === "atlas-bounded-v1" ? `Omitted ${compression.omittedSections.length} bounded sections; recover via ${compression.recoveryRef}.` : null,
      lastContextCheckpoint: new Date().toISOString(),
      maxBytes,
      omitted,
      compression,
    }),
  };
}
