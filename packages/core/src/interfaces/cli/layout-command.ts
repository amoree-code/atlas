import { planLayout } from "../../application/layout/layout-plan.js";
import { oceanRoot } from "../../paths.js";

export async function runLayoutCommand(args: string[]): Promise<void> {
  const action = args[0] ?? "plan";
  if (action !== "plan") throw new Error("Usage: ocean layout plan");
  console.log(JSON.stringify(await planLayout(oceanRoot()), null, 2));
}
