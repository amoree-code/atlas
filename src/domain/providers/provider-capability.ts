import { z } from "zod";

export const providerCapabilitySchema = z.object({
  provider: z.enum(["claude", "codex", "gemini", "antigravity"]),
  command: z.string().min(1), installed: z.boolean(), headless: z.boolean(),
  resume: z.boolean(), streaming: z.boolean(), structuredOutput: z.boolean(),
  authentication: z.enum(["cli-managed", "unknown"]),
});
export type ProviderCapability = z.infer<typeof providerCapabilitySchema>;
