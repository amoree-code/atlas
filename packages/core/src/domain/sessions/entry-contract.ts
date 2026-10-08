import { z } from "zod";

// "atlas-run" is the pre-rename value; read-only: records stored before the rename still carry it. Never written.
const sessionEntryPointSchema = z
  .enum([
    "ocean-run",
    "atlas-run",
    "terminal-shim",
    "interactive-managed",
    "desktop-wrapper",
  ])
  .transform((entryPoint) =>
    entryPoint === "atlas-run" ? "ocean-run" : entryPoint,
  );
const sessionControlLevelSchema = z.enum([
  "full-head",
  "managed-partial",
  "observed",
  "bypass",
]);
const sessionInputCaptureSchema = z.enum([
  "semantic",
  "bounded-terminal",
  "none",
]);

const sessionEntryContractSchema = z.object({
  entryPoint: sessionEntryPointSchema,
  controlLevel: sessionControlLevelSchema,
  inputCapture: sessionInputCaptureSchema,
  contextTransport: z.string().min(1),
  policyEnforcement: z.string().min(1),
  promotion: z.literal("explicit-review"),
  resume: z.string().min(1),
});

export type SessionEntryContract = z.infer<typeof sessionEntryContractSchema>;

export function validateSessionEntryContract(
  contract: SessionEntryContract,
): SessionEntryContract {
  return sessionEntryContractSchema.parse(contract);
}
