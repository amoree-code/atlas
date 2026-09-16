import assert from "node:assert/strict";
import { access, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { createHandoff, getHandoff } from "../dist/application/handoff/handoff-service.js";
import { runAgent } from "../dist/application/runs/run-agent.js";
import { SessionStore } from "../dist/infrastructure/persistence/session-store.js";

test("one bounded handoff keeps semantic context equivalent across all registered clients", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "atlas-t193-"));
  await mkdir(path.join(root, "system", "profiles"), { recursive: true });
  await mkdir(path.join(root, "projects", "atlas", "tickets", "T-193"), { recursive: true });
  await writeFile(path.join(root, "system", "profiles", "universal.json"), JSON.stringify({
    name: "universal", role: "bounded verifier", writePolicy: "none", defaultClient: "claude",
    clients: Object.fromEntries(["claude", "codex", "gemini", "antigravity", "hermes", "kilo", "kimi"].map((client) => [client, {
      enabled: true, capabilities: ["handoff-read"], limitations: client === "claude" ? [] : ["provider-native-resume-not-guaranteed"],
    }])),
  }));
  await writeFile(path.join(root, "projects", "atlas", "tickets", "T-193", "task.md"), `---\nid: T-193\ntitle: Continuity test\nstate: in_progress\nrequirement: Share one bounded task context\n---\n\n## Objective\nKeep context small and provider-neutral.\n`);
  process.env.ATLAS_ROOT = root;
  try {
    const handoff = await createHandoff({ ticketId: "T-193", nextAction: "Run the bounded verification" });
    const seen = [];
    for (const client of ["claude", "codex", "gemini", "antigravity", "hermes", "kilo", "kimi"]) {
      const session = await runAgent({ profileName: "universal", client, ticketId: "T-193", handoffId: handoff.handoffId, prompt: "Continue the task", cwd: root }, async (request) => {
        seen.push({ provider: request.provider, prompt: request.prompt });
        return { exitCode: 0, events: [], stderr: "" };
      });
      assert.equal(session.ticketId, "T-193");
      assert.equal(session.handoffId, handoff.handoffId);
    }
    assert.deepEqual(seen.map((item) => item.provider), ["claude", "codex", "gemini", "antigravity", "hermes", "kilo", "kimi"]);
    assert.ok(seen.every(({ prompt }) => prompt.includes('"ticketId":"T-193"') && prompt.includes("Run the bounded verification") && prompt.includes("handoff-read")));
    const stored = await getHandoff(handoff.handoffId, 2_000);
    assert.ok(Buffer.byteLength(stored.compactContext) <= 2_000);
    const store = new SessionStore(path.join(root, "system", "sessions", "sessions.sqlite"));
    const ideaId = "idea-t193";
    store.saveIdea({ ideaId, title: "Explicit only", content: "This is intentionally captured." });
    assert.equal(store.listIdeas("raw")[0].ideaId, ideaId);
    assert.equal(store.listIdeas("raw").length, 1);
    store.close();
    await assert.rejects(() => access(path.join(root, "personal", "inbox", "INBOX.md")));
  } finally {
    delete process.env.ATLAS_ROOT;
  }
});
