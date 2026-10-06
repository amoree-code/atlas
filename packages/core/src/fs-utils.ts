import { readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import { StringDecoder } from "node:string_decoder";

// Small filesystem/parsing helpers shared across layers, kept alongside paths.ts rather than
// under any single layer since both application and infrastructure code use them directly.

// Atomic write: content lands in a sibling temp file and is renamed into place, so a failure
// (disk full, OOM kill, thrown error) never leaves the target truncated or partially written.
export async function atomicWrite(
  target: string,
  content: string,
): Promise<number> {
  const temp = `${target}.ocean-tmp-${process.pid}-${Date.now()}`;
  try {
    await writeFile(temp, content, "utf8");
    await rename(temp, target);
    return Buffer.byteLength(content, "utf8");
  } catch (error) {
    await rm(temp, { force: true });
    throw error;
  }
}

// Truncates text to at most `maxBytes` UTF-8 bytes without splitting a code point: a partial
// trailing sequence is dropped rather than rendered as U+FFFD. Callers compare lengths to
// detect truncation and append their own marker.
export function truncateUtf8(text: string, maxBytes: number): string {
  if (Buffer.byteLength(text) <= maxBytes) return text;
  if (maxBytes <= 0) return "";
  return new StringDecoder("utf8").write(
    Buffer.from(text).subarray(0, maxBytes),
  );
}

// Parses JSON that may be malformed or may not be an object (e.g. a bare string/number) —
// returns null instead of throwing, so a caller reading an untrusted or legacy field never
// needs its own try/catch.
export function safeJsonParse(value: string): Record<string, unknown> | null {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

// Parses a `---\n...\n---` frontmatter block into a flat field map. First occurrence of a
// key wins; values are trimmed and stripped of one layer of surrounding quotes. Exported for
// the brain markdown layer (application/brain/brain-markdown.ts), which needs the raw block
// text too (for nested `metadata:` and block-list `tags:`), not just the flattened map this
// function returns.
export function parseFrontmatter(source: string): Record<string, string> {
  // Normalized up front: a per-line regex below anchors on `$` (end of string), which a
  // trailing `\r` from CRLF-checked-out files (e.g. a Windows git checkout) defeats — `.`
  // excludes line terminators, so the line never reaches `$` and silently fails to match.
  const normalized = source.replace(/\r\n/g, "\n");
  if (!normalized.startsWith("---")) return {};
  const end = normalized.indexOf("\n---", 3);
  const block = end < 0 ? normalized.slice(3) : normalized.slice(3, end);
  const fields: Record<string, string> = {};
  for (const line of block.split("\n")) {
    const match = /^\s{0,2}([A-Za-z_][\w-]*):\s*(.*)$/.exec(line);
    if (!match) continue;
    if (fields[match[1]] === undefined)
      fields[match[1]] = match[2].trim().replace(/^["']|["']$/g, "");
  }
  return fields;
}

export async function readFrontmatterFile(
  file: string,
  readBytes: number,
): Promise<{
  fields: Record<string, string>;
  mtimeMs: number;
  size: number;
} | null> {
  try {
    const info = await stat(file);
    if (!info.isFile()) return null;
    const handle = await readFile(file, "utf8");
    return {
      fields: parseFrontmatter(handle.slice(0, readBytes)),
      mtimeMs: info.mtimeMs,
      size: info.size,
    };
  } catch {
    return null;
  }
}
