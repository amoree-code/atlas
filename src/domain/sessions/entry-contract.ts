import { z } from "zod";

export const sessionEntryPointSchema = z.enum([
  "atlas-run",
  "terminal-shim",
  "interactive-managed",
  "desktop-wrapper",
]);
export const sessionControlLevelSchema = z.enum([
  "full-head",
  "managed-partial",
  "observed",
  "bypass",
]);
export const sessionInputCaptureSchema = z.enum([
  "semantic",
  "bounded-terminal",
  "none",
]);

export const sessionEntryContractSchema = z.object({
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
