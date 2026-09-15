// An in-memory BrowserProvider used by tests to exercise application-layer policy
// (authority, approval, verification) without launching a real browser.

import type { BrowserElement, BrowserHandle, BrowserLaunch, BrowserProvider } from "./browser-provider.js";

class FakePage {
  url = "about:blank";
  title = "";
  inputs = new Map<string, string>();
  elements: BrowserElement[] = [];
  scrollY = 0;
  clickTargets = new Map<string, string>();
}

class FakeHandle implements BrowserHandle {
  constructor(private readonly page: FakePage) {}

  // Test-only configuration hooks, not part of the BrowserHandle contract: they let a
  // test script a scenario (a click that navigates, or a selector's current element
  // count) for the application layer to verify against, without a real browser.
  setElements(elements: BrowserElement[]): void { this.page.elements = elements; }
  setClickTarget(selector: string, url: string): void { this.page.clickTargets.set(selector, url); }

  async state() { return { url: this.page.url, title: this.page.title }; }

  async navigate(url: string) {
    this.page.url = url;
    this.page.title = `Title for ${url}`;
    return this.state();
  }

  async readText() { return { ...(await this.state()), text: this.page.elements.map((element) => element.text).join(" ") }; }

  async observe() { return { ...(await this.state()), elements: this.page.elements }; }

  async extract(selector: string, attribute: string | null) {
    const values = this.page.elements
      .filter((element) => element.id === selector || element.name === selector)
      .map((element) => (attribute ? null : element.text));
    return { selector, count: values.length, values };
  }

  async click(selector: string) {
    const urlBefore = this.page.url;
    const target = this.page.clickTargets.get(selector);
    if (target) {
      this.page.url = target;
      this.page.title = `Title for ${target}`;
    }
    return { ...(await this.state()), urlBefore };
  }

  async type(selector: string, text: string, clear = true) {
    const current = clear ? "" : (this.page.inputs.get(selector) ?? "");
    const value = current + text;
    this.page.inputs.set(selector, value);
    return { selector, typed: text.length, value };
  }

  async select(selector: string, value: string) {
    this.page.inputs.set(selector, value);
    return { selector, value };
  }

  async scroll(deltaY = 0) {
    this.page.scrollY = Math.max(0, this.page.scrollY + deltaY);
    return { scrollY: this.page.scrollY };
  }

  async wait() { return this.state(); }

  async upload(selector: string, paths: string[]) {
    this.page.inputs.set(selector, paths.join(","));
    return { selector, attached: paths.map((filePath) => filePath.split("/").pop() ?? filePath) };
  }

  async download(selector: string, destinationDir: string) {
    return { selector, path: `${destinationDir}/fake-download.txt`, size: 0 };
  }

  async submit(selector: string) {
    const urlBefore = this.page.url;
    return { ...(await this.state()), urlBefore };
  }

  async release() {}
}

export class FakeBrowserProvider implements BrowserProvider {
  private readonly pages = new Map<string, FakePage>();
  launchCount = 0;

  async detect() { return { ok: true, detail: "fake provider always available" }; }

  async launch(profileDir: string, port = 0): Promise<BrowserLaunch> {
    this.launchCount += 1;
    const launch = { pid: this.launchCount, port, endpoint: `fake://${profileDir}`, profileDir };
    this.pages.set(launch.endpoint, new FakePage());
    return launch;
  }

  async connect(launch: BrowserLaunch): Promise<BrowserHandle> {
    const page = this.pages.get(launch.endpoint);
    if (!page) throw new Error(`No fake session for endpoint: ${launch.endpoint}`);
    return new FakeHandle(page);
  }

  async close(launch: BrowserLaunch): Promise<void> {
    this.pages.delete(launch.endpoint);
  }
}
