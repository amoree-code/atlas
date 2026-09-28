import { z } from "zod";

export const skillMetadataSchema = z.object({
  name: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
  description: z.string().min(1),
  version: z.string().min(1),
  category: z.enum(["core", "role", "project", "personal"]),
});

export type SkillMetadata = z.infer<typeof skillMetadataSchema>;

export const skillSchema = skillMetadataSchema.extend({
  instructions: z.string().min(1),
});

export type Skill = z.infer<typeof skillSchema>;
