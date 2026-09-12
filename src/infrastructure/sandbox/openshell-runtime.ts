import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { runInteractive, type InteractiveProcessResult } from "../process/interactive-process.js";
import { runHeadless } from "../process/cli-process.js";
import { atlasPath } from "../../paths.js";
import type { SandboxLaunchRequest, SandboxLaunchResult, SandboxRuntime } from "./sandbox-runtime.js";

export function buildOpenShellInvocation(request: SandboxLaunchRequest, policyPath: string): { command: string; args: string[] } {
  const providerMode = request.environment?.ATLAS_OPENSHELL_AUTO_PROVIDERS === "1"
    ? "--auto-providers"
    : "--no-auto-providers";
  const provider = request.environment?.ATLAS_OPENSHELL_PROVIDER;
  return {
    command: "openshell",
    args: ["sandbox", "create", "--no-keep", providerMode, ...(provider ? ["--provider", provider] : []), "--policy", policyPath, "--", request.command, ...request.args],
  };
}

export async function writeOpenShellPolicy(request: SandboxLaunchRequest): Promise<{ directory: string; policyPath: string }> {
  const root = atlasPath("runtime", "temporary");
  await mkdir(root, { recursive: true });
  const directory = await mkdtemp(path.join(root, "openshell-"));
  const policyPath = path.join(directory, "policy.yaml");
  const policy = [
    "version: 1",
    "filesystem_policy:",
    "  include_workdir: true",
    "  read_only:",
    "    - /usr",
    "    - /bin",
    "    - /sbin",
    "    - /lib",
    "    - /etc",
    "  read_write:",
    "    - /tmp",
    "landlock:",
    "  compatibility: best_effort",
    ...providerNetworkPolicy(request.command),
    `# Atlas cwd: ${request.cwd}`,
    "",
  ].join("\n");
  await writeFile(policyPath, policy, { mode: 0o600 });
  return { directory, policyPath };
}

function providerNetworkPolicy(command: string): string[] {
  if (path.basename(command) !== "codex") return [];

  return [
    "network_policies:",
    "  codex:",
    "    name: codex",
    "    endpoints:",
    "      - host: api.openai.com",
    "        port: 443",
    "        protocol: rest",
    "        enforcement: enforce",
    "        access: read-write",
    "      - host: chatgpt.com",
    "        port: 443",
    "        protocol: rest",
    "        enforcement: enforce",
    "        access: read-write",
    "      - host: auth.openai.com",
    "        port: 443",
    "        protocol: rest",
    "        enforcement: enforce",
    "        access: read-write",
    "      - host: ab.chatgpt.com",
    "        port: 443",
    "        protocol: rest",
    "        enforcement: enforce",
    "        access: read-write",
    "    binaries:",
    "      - path: /usr/bin/codex",
    "      - path: /usr/bin/node",
    "      - path: /usr/lib/node_modules/@openai/**",
  ];
}

export class OpenShellRuntime implements SandboxRuntime {
  readonly id = "openshell";

  async launch(request: SandboxLaunchRequest): Promise<SandboxLaunchResult> {
    const { directory, policyPath } = await writeOpenShellPolicy(request);
    try {
      const invocation = buildOpenShellInvocation(request, policyPath);
      const result = await runHeadless({ command: invocation.command, args: invocation.args, cwd: request.cwd, env: request.environment });
      return { exitCode: result.exitCode, output: [...result.events, result.stderr].map(String).join("\n"), runtime: this.id };
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }

  async launchInteractive(request: SandboxLaunchRequest): Promise<InteractiveProcessResult> {
    const { directory, policyPath } = await writeOpenShellPolicy(request);
    try {
      const invocation = buildOpenShellInvocation(request, policyPath);
      return await runInteractive({ command: invocation.command, args: invocation.args, cwd: request.cwd, env: request.environment });
    } finally {
      await rm(directory, { recursive: true, force: true });
    }
  }
}
