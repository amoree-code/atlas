import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { PlaywrightBrowserProvider } from "../dist/infrastructure/providers/playwright-browser-provider.js";

test("real Playwright browser lifecycle and basic operations", {
  skip: process.env.ATLAS_BROWSER_INTEGRATION !== "1",
}, async () => {
  const profileDir = await mkdtemp(
    path.join(os.tmpdir(), "atlas-browser-integration-"),
  );
  const provider = new PlaywrightBrowserProvider();
  const detected = await provider.detect();
  assert.equal(detected.ok, true, detected.detail);

  const launch = await provider.launch(profileDir);
  let handle;
  try {
    handle = await provider.connect(launch);
    const page = await handle.navigate(
      "data:text/html,<button id='go'>Go</button><main>Atlas browser</main>",
    );
    assert.match(page.url, /^data:text\/html/);
    assert.equal(
      (await handle.extract("main", null)).values[0],
      "Atlas browser",
    );
    await handle.click("#go");
    assert.equal(
      (await handle.observe()).elements.some((element) => element.id === "go"),
      true,
    );
  } finally {
    await handle?.release().catch(() => undefined);
    await provider.close(launch).catch(() => undefined);
    await rm(profileDir, { recursive: true, force: true });
  }
});
