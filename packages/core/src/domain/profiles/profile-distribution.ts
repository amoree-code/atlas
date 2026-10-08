import { z } from "zod";

const profileDistributionSchema = z
  .object({
    name: z.string().min(1),
    version: z.string().min(1),
    description: z.string().default(""),
    oceanRequires: z.string().optional(),
    // "atlasRequires" is the pre-rename key; read-only: records stored before the rename still carry it. Never written.
    atlasRequires: z.string().optional(),
    clients: z.array(z.string().min(1)).default([]),
    files: z.array(z.string().min(1)).default([]),
    distributionOwned: z.array(z.string().min(1)).default(["profile.json"]),
  })
  .transform(({ atlasRequires, oceanRequires, ...rest }) => ({
    ...rest,
    oceanRequires: oceanRequires ?? atlasRequires ?? "*",
  }));

export type ProfileDistribution = z.infer<typeof profileDistributionSchema>;

export function validateProfileDistribution(
  input: unknown,
): ProfileDistribution {
  return profileDistributionSchema.parse(input);
}
