import { z } from "zod";

export const mcpToolSchema = z.object({
  name: z.string().min(1), description: z.string().optional(), inputSchema: z.record(z.unknown()).optional(),
  annotations: z.object({ readOnlyHint: z.boolean().optional() }).optional(),
});
export type McpTool = z.infer<typeof mcpToolSchema>;
export type McpApproval = { approved: boolean };
