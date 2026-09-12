export type SandboxLaunchRequest = {
  command: string;
  args: string[];
  cwd: string;
  environment?: Record<string, string>;
  policyVersion?: string;
};

export type SandboxLaunchResult = {
  exitCode: number;
  output: string;
  runtime: string;
};

// The first interception slice uses the local interactive process directly. OpenShell can
// implement this boundary later without moving authority, sessions, or provider selection
// into the sandbox runtime.
export interface SandboxRuntime {
  readonly id: string;
  launch(request: SandboxLaunchRequest): Promise<SandboxLaunchResult>;
}
