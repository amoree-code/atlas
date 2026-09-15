// The only file in Atlas permitted to know a browser engine. Everything above the
// BrowserProvider boundary (browser-provider.ts) stays engine-neutral.
//
// Depends on `playwright-core`, not `playwright`: playwright-core ships the driver and
// API without downloading a Chromium binary on install, so `pnpm install` stays light and
// a missing browser binary is a reportable `detect()` failure rather than an install-time
// requirement.
//
// A session survives between CLI invocations: the browser is launched as its own
// detached process with a remote-debugging port, and later invocations reconnect over
// CDP by port. Without this, a multi-step browser task would mean a new browser per
// step, which is not a session.

import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { spawn } from "node:child_process";
import net from "node:net";
import path from "node:path";
import type { Browser, BrowserContext, Page } from "playwright-core";
import type { BrowserElement, BrowserHandle, BrowserLaunch, BrowserProvider } from "./browser-provider.js";

// A download's suggested filename comes from the remote page/server (e.g. a
// Content-Disposition header) and must never be trusted as a path: it can contain `../`,
// an absolute path, or backslash separators aimed at escaping destinationDir.
export function safeDownloadFilename(suggested: string): string {
  const normalized = suggested.replace(/\\/g, "/");
  const base = path.posix.basename(normalized).trim();
  return !base || base === "." || base === ".." ? "download" : base;
}

export function resolveDownloadPath(destinationDir: string, suggestedFilename: string): string {
  const resolvedDir = path.resolve(destinationDir);
  const candidate = path.resolve(resolvedDir, safeDownloadFilename(suggestedFilename));
  if (candidate !== resolvedDir && !candidate.startsWith(resolvedDir + path.sep)) {
    throw new Error(`Download path escapes destination directory: ${suggestedFilename}`);
  }
  return candidate;
}

async function freePort(): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => resolve(port));
    });
  });
}

async function fetchWebSocketDebuggerUrl(port: number): Promise<string | null> {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(1000) });
    const body = (await response.json()) as { webSocketDebuggerUrl?: string };
    return body.webSocketDebuggerUrl ?? null;
  } catch {
    return null;
  }
}

function resolveChromiumExecutable(): string | null {
  const candidates = [
    process.env.ATLAS_BROWSER_EXECUTABLE,
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
  ].filter((candidate): candidate is string => Boolean(candidate));
  return candidates.find((candidate) => existsSync(candidate)) ?? null;
}

export class PlaywrightBrowserProvider implements BrowserProvider {
  async detect(): Promise<{ ok: boolean; detail: string }> {
    const executable = resolveChromiumExecutable();
    if (!executable) return { ok: false, detail: "no Chromium-family browser binary found; set ATLAS_BROWSER_EXECUTABLE" };
    return { ok: true, detail: executable };
  }

  async launch(profileDir: string, port?: number): Promise<BrowserLaunch> {
    const executable = resolveChromiumExecutable();
    if (!executable) throw new Error("Browser capability denied: no browser binary detected");
    const resolvedPort = port ?? (await freePort());
    await mkdir(profileDir, { recursive: true });
    const child = spawn(executable, [
      `--remote-debugging-port=${resolvedPort}`,
      `--remote-debugging-address=127.0.0.1`,
      `--user-data-dir=${profileDir}`,
      "--no-first-run", "--no-default-browser-check", "--headless=new", "--disable-gpu", "about:blank",
    ], { stdio: "ignore", detached: true });
    child.unref();
    let endpoint: string | null = null;
    for (let attempt = 0; attempt < 100 && !endpoint; attempt += 1) {
      endpoint = await fetchWebSocketDebuggerUrl(resolvedPort);
      if (!endpoint) await new Promise((resolve) => setTimeout(resolve, 200));
    }
    if (!endpoint) {
      child.kill();
      throw new Error("Browser did not expose a debugging endpoint within the timeout");
    }
    return { pid: child.pid ?? -1, port: resolvedPort, endpoint, profileDir };
  }

  async connect(launch: BrowserLaunch): Promise<BrowserHandle> {
    const { chromium } = await import("playwright-core");
    const browser = await chromium.connectOverCDP(`http://127.0.0.1:${launch.port}`);
    const context: BrowserContext = browser.contexts()[0] ?? (await browser.newContext());
    const page: Page = context.pages()[0] ?? (await context.newPage());
    return new PlaywrightHandle(browser, page);
  }

  async close(launch: BrowserLaunch): Promise<void> {
    if (launch.pid > 0) {
      try { process.kill(launch.pid, "SIGTERM"); } catch { /* already exited */ }
    }
  }
}

class PlaywrightHandle implements BrowserHandle {
  constructor(private readonly browser: Browser, private readonly page: Page) {}

  async state() { return { url: this.page.url(), title: await this.page.title() }; }

  async navigate(url: string, timeoutMs = 30_000) {
    await this.page.goto(url, { timeout: timeoutMs, waitUntil: "domcontentloaded" });
    return this.state();
  }

  async readText() {
    const text = (await this.page.innerText("body")).slice(0, 20_000);
    return { ...(await this.state()), text };
  }

  async observe() {
    const elements = (await this.page.$$eval(
      "a,button,input,select,textarea,[role=button]",
      (nodes) => nodes.slice(0, 120).map((node) => {
        const element = node as HTMLInputElement;
        return {
          tag: element.tagName.toLowerCase(),
          type: (element as { type?: string }).type ?? null,
          name: element.name || null,
          id: element.id || null,
          text: (element.innerText || element.value || "").trim().slice(0, 80),
          visible: Boolean(element.offsetWidth || element.offsetHeight),
        };
      }),
    )) as BrowserElement[];
    return { ...(await this.state()), elements };
  }

  async extract(selector: string, attribute: string | null) {
    const values = attribute
      ? await this.page.$$eval(selector, (nodes, attr) => nodes.map((node) => node.getAttribute(attr)), attribute)
      : await this.page.$$eval(selector, (nodes) => nodes.map((node) => (node as HTMLInputElement).innerText?.trim() || (node as HTMLInputElement).value?.trim() || ""));
    return { selector, count: values.length, values: values.slice(0, 200) };
  }

  async click(selector: string, timeoutMs = 15_000) {
    const urlBefore = this.page.url();
    await this.page.click(selector, { timeout: timeoutMs });
    await this.page.waitForTimeout(300);
    return { ...(await this.state()), urlBefore };
  }

  async type(selector: string, text: string, clear = true) {
    if (clear) await this.page.fill(selector, "", { timeout: 15_000 });
    await this.page.type(selector, text, { timeout: 15_000 });
    const value = await this.page.inputValue(selector, { timeout: 5_000 });
    return { selector, typed: text.length, value };
  }

  async select(selector: string, value: string) {
    await this.page.selectOption(selector, value, { timeout: 15_000 });
    return { selector, value: await this.page.inputValue(selector, { timeout: 5_000 }) };
  }

  async scroll(deltaY = 600) {
    await this.page.mouse.wheel(0, deltaY);
    await this.page.waitForTimeout(150);
    const scrollY = await this.page.evaluate(() => Math.round(window.scrollY));
    return { scrollY };
  }

  async wait(options: { selector?: string; urlContains?: string; timeoutMs?: number }) {
    const timeout = options.timeoutMs ?? 15_000;
    if (options.selector) await this.page.waitForSelector(options.selector, { timeout });
    if (options.urlContains) await this.page.waitForURL(`**${options.urlContains}**`, { timeout });
    return this.state();
  }

  async upload(selector: string, paths: string[]) {
    await this.page.setInputFiles(selector, paths, { timeout: 15_000 });
    const attached = await this.page.$eval(selector, (node) => Array.from((node as HTMLInputElement).files ?? []).map((file) => file.name));
    return { selector, attached };
  }

  async download(selector: string, destinationDir: string, timeoutMs = 60_000) {
    const [download] = await Promise.all([
      this.page.waitForEvent("download", { timeout: timeoutMs }),
      this.page.click(selector, { timeout: timeoutMs }),
    ]);
    await mkdir(destinationDir, { recursive: true });
    const targetPath = resolveDownloadPath(destinationDir, download.suggestedFilename());
    await download.saveAs(targetPath);
    const { statSync } = await import("node:fs");
    const size = existsSync(targetPath) ? statSync(targetPath).size : 0;
    return { selector, path: targetPath, size };
  }

  async submit(selector: string, timeoutMs = 20_000) {
    const urlBefore = this.page.url();
    await this.page.click(selector, { timeout: timeoutMs });
    try { await this.page.waitForLoadState("domcontentloaded", { timeout: timeoutMs }); } catch { /* best-effort */ }
    await this.page.waitForTimeout(400);
    return { ...(await this.state()), urlBefore };
  }

  async release() {
    await this.browser.close();
  }
}
