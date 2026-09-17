import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { atlasPath, resolveWithin } from "../../paths.js";

const policyRoot = () => atlasPath("system", "control-plane", "governance", "policies");
const rulesFile = () => atlasPath("system", "control-plane", "governance", "rules", "core.md");

async function policyNames(): Promise<string[]> {
  return (await readdir(policyRoot(), { withFileTypes: true }))
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md") && entry.name !== "README.md")
    .map((entry) => entry.name.slice(0, -3)).sort();
}

export async function runPolicyCommand(name = "list"): Promise<void> {
  const names = await policyNames();
  if (name === "list") {
    console.log(JSON.stringify({ policies: names }, null, 2));
    return;
  }
  if (name === "doctor") {
    const core = await readFile(rulesFile(), "utf8");
    const referenced = new Set([...core.matchAll(/atlas policy ([a-z-]+)/g)].map((match) => match[1]).filter((item) => item !== "list"));
    const missing = [...referenced].filter((item) => !names.includes(item));
    console.log(JSON.stringify({ ok: missing.length === 0, policies: names.length, missing }, null, 2));
    if (missing.length) process.exitCode = 1;
    return;
  }
  if (!/^[a-z][a-z-]*$/.test(name) || !names.includes(name)) throw new Error(`Unknown policy: ${name}`);
  process.stdout.write(await readFile(resolveWithin(policyRoot(), `${name}.md`), "utf8"));
}

export async function runLifecycleCommand(args: string[]): Promise<void> {
  const ticketIndex = args.indexOf("--ticket");
  const ticketId = ticketIndex >= 0 ? args[ticketIndex + 1] : undefined;
  const verificationIndex = args.indexOf("--verification");
  const verification = verificationIndex >= 0 ? args[verificationIndex + 1] : undefined;
  const complete = args.includes("--complete");
  const decision = complete && verification === "passed" ? "CHECKPOINT" : "CONTINUE";
  const result = { decision, ticketId: ticketId ?? null, complete, verification: verification ?? "unknown", reason: decision === "CHECKPOINT" ? "completed work with passing verification must be persisted" : "no verified completion boundary was supplied" };
  if (args.includes("--json")) console.log(JSON.stringify(result, null, 2));
  else console.log(`${result.decision}: ${result.reason}`);
}
