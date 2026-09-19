import { randomUUID } from "node:crypto";
import { mkdir } from "node:fs/promises";
import { validateSessionEntryContract } from "../../domain/sessions/entry-contract.js";
import type { Session, SessionEvent } from "../../domain/sessions/session.js";
import type { SessionStore } from "../../infrastructure/persistence/session-store.js";
import type {
  BrowserHandle,
  BrowserLaunch,
} from "../../infrastructure/providers/browser-provider.js";
import { atlasPath, atlasRoot } from "../../paths.js";
import type { BrowserService, ClickExpectation } from "./browser-service.js";

type BrowserResumeData = BrowserLaunch & {
  profileKey: string;
  provider: "playwright";
};

function safeProfileKey(value: string): string {
  const key = value.trim();
  if (
    !key ||
    key === "." ||
    key === ".." ||
    !/^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$/.test(key)
  ) {
    throw new Error(
      "Browser profile key must contain only letters, numbers, hyphens, and underscores.",
    );
  }
  return key;
}

function parseResumeData(session: Session): BrowserResumeData {
  if (session.provider !== "browser" || !session.resumeData)
    throw new Error(
      `Browser session is not reconnectable: ${session.sessionId}`,
    );
  try {
    const value = JSON.parse(session.resumeData) as BrowserResumeData;
    if (
      !value.profileDir ||
      value.port === undefined ||
      value.pid === undefined ||
      value.provider !== "playwright"
    )
      throw new Error("incomplete browser metadata");
    return value;
  } catch {
    throw new Error(
      `Browser session metadata is invalid: ${session.sessionId}`,
    );
  }
}

export class BrowserSessionManager {
  constructor(
    private readonly store: SessionStore,
    private readonly service: BrowserService,
  ) {}

  async detect(): Promise<{ ok: boolean; detail: string }> {
    return this.service.detect();
  }

  async open(profileKey = "default", port?: number): Promise<Session> {
    const key = safeProfileKey(profileKey);
    const sessionId = randomUUID();
    const profileDir = atlasPath("system", "browser", "profiles", key);
    await mkdir(profileDir, { recursive: true });
    this.store.create({
      sessionId,
      provider: "browser",
      providerSessionId: `browser:${key}:${sessionId}`,
      parentSessionId: null,
      profile: "browser",
      profileIdentity: "browser-v1",
      workingDirectory: atlasRoot(),
      resumeData: null,
    });
    this.store.appendEvent(
      sessionId,
      "session_entry_contract",
      JSON.stringify(
        validateSessionEntryContract({
          entryPoint: "atlas-run",
          controlLevel: "full-head",
          inputCapture: "semantic",
          contextTransport: "browser-capability-contract",
          policyEnforcement: "browser-approval-and-post-condition-contract",
          promotion: "explicit-review",
          resume: "browser-profile-session",
        }),
      ),
    );
    try {
      const launch = await this.service.launch(profileDir, port);
      const resumeData: BrowserResumeData = {
        ...launch,
        profileKey: key,
        provider: "playwright",
      };
      this.store.updateStatus(sessionId, "running", JSON.stringify(resumeData));
      this.store.appendEvent(
        sessionId,
        "browser_opened",
        JSON.stringify({ profileKey: key, port: launch.port, pid: launch.pid }),
      );
      return this.requireSession(sessionId);
    } catch (error) {
      this.store.updateStatus(sessionId, "failed");
      this.store.appendEvent(
        sessionId,
        "error",
        error instanceof Error ? error.message : String(error),
      );
      throw error;
    }
  }

  show(sessionId: string): Session {
    return this.requireSession(sessionId);
  }

  events(sessionId: string): SessionEvent[] {
    this.requireSession(sessionId);
    return this.store.listEvents(sessionId);
  }

  async close(sessionId: string): Promise<Session> {
    const session = this.requireSession(sessionId);
    if (session.status === "completed") return session;
    const launch = parseResumeData(session);
    try {
      await this.service.close(launch);
      this.store.updateStatus(sessionId, "completed");
      this.store.appendEvent(
        sessionId,
        "browser_closed",
        JSON.stringify({ pid: launch.pid, port: launch.port }),
      );
      return this.requireSession(sessionId);
    } catch (error) {
      this.store.updateStatus(sessionId, "failed");
      this.store.appendEvent(
        sessionId,
        "error",
        error instanceof Error ? error.message : String(error),
      );
      throw error;
    }
  }

  async navigate(
    sessionId: string,
    url: string,
    approved: boolean,
    timeoutMs?: number,
  ) {
    return this.withHandle(sessionId, "navigate", (handle) =>
      this.service.navigate(handle, url, { approved, timeoutMs }),
    );
  }

  async read(sessionId: string) {
    return this.withHandle(sessionId, "read", (handle) => handle.readText());
  }
  async observe(sessionId: string) {
    return this.withHandle(sessionId, "observe", (handle) => handle.observe());
  }
  async extract(sessionId: string, selector: string, attribute: string | null) {
    return this.withHandle(sessionId, "extract", (handle) =>
      handle.extract(selector, attribute),
    );
  }
  async click(
    sessionId: string,
    selector: string,
    expectation: ClickExpectation,
    timeoutMs?: number,
  ) {
    return this.withHandle(sessionId, "click", (handle) =>
      this.service.click(handle, selector, expectation, timeoutMs),
    );
  }
  async type(
    sessionId: string,
    selector: string,
    text: string,
    clear: boolean,
  ) {
    return this.withHandle(sessionId, "type", (handle) =>
      this.service.type(handle, selector, text, clear),
    );
  }
  async select(sessionId: string, selector: string, value: string) {
    return this.withHandle(sessionId, "select", (handle) =>
      this.service.select(handle, selector, value),
    );
  }
  async scroll(sessionId: string, deltaY: number) {
    return this.withHandle(sessionId, "scroll", (handle) =>
      handle.scroll(deltaY),
    );
  }
  async wait(
    sessionId: string,
    options: { selector?: string; urlContains?: string; timeoutMs?: number },
  ) {
    return this.withHandle(sessionId, "wait", (handle) => handle.wait(options));
  }
  async upload(
    sessionId: string,
    selector: string,
    paths: string[],
    approved: boolean,
  ) {
    return this.withHandle(sessionId, "upload", (handle) =>
      this.service.upload(handle, selector, paths, { approved }),
    );
  }
  async download(
    sessionId: string,
    selector: string,
    destinationDir: string,
    approved: boolean,
    timeoutMs?: number,
  ) {
    return this.withHandle(sessionId, "download", (handle) =>
      this.service.download(handle, selector, destinationDir, {
        approved,
        timeoutMs,
      }),
    );
  }
  async submit(
    sessionId: string,
    selector: string,
    approved: boolean,
    timeoutMs?: number,
  ) {
    return this.withHandle(sessionId, "submit", (handle) =>
      this.service.submit(handle, selector, { approved, timeoutMs }),
    );
  }

  private async withHandle<T>(
    sessionId: string,
    operationName: string,
    operation: (handle: BrowserHandle) => Promise<T>,
  ): Promise<T> {
    const session = this.requireSession(sessionId, false);
    const launch = parseResumeData(session);
    let handle: BrowserHandle | undefined;
    try {
      try {
        handle = await this.service.connect(launch);
      } catch (error) {
        this.store.updateStatus(sessionId, "failed");
        this.store.appendEvent(
          sessionId,
          "browser_unreachable",
          JSON.stringify({
            error: error instanceof Error ? error.message : String(error),
          }),
        );
        throw error;
      }
      const result = await operation(handle);
      this.store.appendEvent(
        sessionId,
        "browser_operation",
        JSON.stringify({
          operation: operationName,
          result: summarizeResult(result),
        }),
      );
      return result;
    } catch (error) {
      this.store.appendEvent(
        sessionId,
        "browser_operation_failed",
        JSON.stringify({
          error: error instanceof Error ? error.message : String(error),
        }),
      );
      throw error;
    } finally {
      await handle?.release().catch(() => undefined);
    }
  }

  private requireSession(sessionId: string, allowCompleted = true): Session {
    const session = this.store.get(sessionId);
    if (!session) throw new Error(`Browser session not found: ${sessionId}`);
    if (session.provider !== "browser")
      throw new Error(`Session is not a browser session: ${sessionId}`);
    if (
      session.status !== "running" &&
      (!allowCompleted || session.status !== "completed")
    )
      throw new Error(`Browser session is not available: ${session.status}`);
    return session;
  }
}

function summarizeResult(value: unknown): unknown {
  if (!value || typeof value !== "object") return value;
  const result = value as Record<string, unknown>;
  return {
    operation: result.operation,
    approved: result.approved,
    verified: result.verified,
    result:
      result.result && typeof result.result === "object"
        ? {
            url: (result.result as Record<string, unknown>).url,
            title: (result.result as Record<string, unknown>).title,
            size: (result.result as Record<string, unknown>).size,
          }
        : undefined,
  };
}

export function browserDownloadsPath(sessionId: string): string {
  return atlasPath("system", "browser", "downloads", sessionId);
}
