import { z } from "zod";

export const contextManifestSchema = z.object({
  files: z.array(z.string()),
  bytes: z.number().int().nonnegative(),
  compactedSummary: z.string().nullable(),
  lastContextCheckpoint: z.string().min(1),
});

export type ContextManifest = z.infer<typeof contextManifestSchema>;
