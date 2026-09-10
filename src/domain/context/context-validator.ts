import { contextManifestSchema, type ContextManifest } from "./context.js";

export function validateContextManifest(input: unknown): ContextManifest {
  return contextManifestSchema.parse(input);
}
