// T-245 Phase 0 — characterization tests.
//
// These pin what the profile / provider / memory code does TODAY, before any production edit.
// Tests marked "GAP" assert a behaviour T-245 intends to change; when a later phase fixes it,
// that phase flips the assertion in the same commit. A failure here means behaviour moved —
// decide whether that was intended, don't just update the expectation.
import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import {
  profileFactsFile,
  readProfileFacts,
  writeProfileFact,
} from "../dist/application/memory/profile-facts.js";
import { formatProfileContract } from "../dist/application/runs/prompt-assembly.js";
import {
  profileIdentity,
  selectProfileClient,
} from "../dist/domain/profiles/profile.js";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";
import { loadProfile } from "../dist/infrastructure/filesystem/profile-loader.js";
import {
  buildProviderInvocation,
  providerAdapterRegistry,
} from "../dist/infrastructure/providers/providers.js";
import { SYSTEM_DIR } from "../dist/paths.js";

const unixOnly = process.platform === "win32" ? test.skip : test;

async function withRoot(fn) {
  const root = await mkdtemp(path.join(os.tmpdir(), "t245-char-"));
  await mkdir(path.join(root, SYSTEM_DIR, "profiles"), { recursive: true });
  const previous = process.env.OCEAN_ROOT;
  const previousLegacy = process.env.ATLAS_ROOT;
  delete process.env.OCEAN_ROOT;
  process.env.ATLAS_ROOT = root;
  try {
    return await fn(root);
  } finally {
    if (previous === undefined) delete process.env.OCEAN_ROOT;
    else process.env.OCEAN_ROOT = previous;
    if (previousLegacy === undefined) delete process.env.ATLAS_ROOT;
    else process.env.ATLAS_ROOT = previousLegacy;
  }
}

const multiClient = () =>
  validateProfile({
    name: "multi",
    role: "assistant",
    model: "profile-model",
    defaultClient: "codex",
    clients: {
      claude: { enabled: true, model: "claude-model" },
      codex: { enabled: true, model: "codex-model" },
      gemini: { enabled: false },
    },
  });

// ---- client routing -----------------------------------------------------------------------

test("client precedence: explicit request, then defaultClient, then provider", () => {
  const profile = multiClient();
  assert.equal(selectProfileClient(profile, "claude").provider, "claude");
  assert.equal(selectProfileClient(profile).provider, "codex");
  const single = validateProfile({
    name: "single",
    role: "r",
    provider: "claude",
    model: "m",
  });
  assert.equal(selectProfileClient(single).provider, "claude");
});

test("the selected client's model overrides the profile model", () => {
  const profile = multiClient();
  assert.equal(selectProfileClient(profile, "claude").model, "claude-model");
  assert.equal(selectProfileClient(profile).model, "codex-model");
});

test("a disabled or unsupported client fails closed", () => {
  const profile = multiClient();
  assert.throws(
    () => selectProfileClient(profile, "gemini"),
    /not enabled for profile/,
  );
  assert.throws(() => selectProfileClient(profile, "deepseek"), /Unsupported/);
});

test("GAP: DeepSeek and OpenRouter are not registered providers", () => {
  assert.deepEqual(Object.keys(providerAdapterRegistry).sort(), [
    "antigravity",
    "claude",
    "codex",
    "gemini",
    "hermes",
    "kilo",
    "kimi",
  ]);
});

// ---- model selection ----------------------------------------------------------------------

test("GAP: the selected model is prompt text only — no provider request carries it", () => {
  const selected = selectProfileClient(multiClient(), "claude");
  assert.match(
    formatProfileContract(selected, { taskId: null, handoffId: null }),
    /model: claude-model/,
  );
  // A provider request has no model field, and no adapter turns a model into a CLI flag.
  const invocation = buildProviderInvocation({
    provider: "claude",
    prompt: "hello",
    cwd: "/tmp",
    model: "claude-model",
  });
  assert.ok(!invocation.args.includes("claude-model"));
  assert.ok(!invocation.args.includes("--model"));
});

// ---- profile identity ---------------------------------------------------------------------

test("profile identity is deterministic and changes with the client model binding", () => {
  const a = multiClient();
  const b = multiClient();
  assert.equal(profileIdentity(a), profileIdentity(b));
  assert.match(profileIdentity(a), /^[0-9a-f]{64}$/);
  const changed = validateProfile({
    ...JSON.parse(JSON.stringify(a)),
    clients: { ...a.clients, codex: { ...a.clients.codex, model: "other" } },
  });
  assert.notEqual(profileIdentity(a), profileIdentity(changed));
});

test("memory.scope is a free-form string today, not a closed enum", () => {
  const profile = validateProfile({
    name: "p",
    role: "r",
    provider: "claude",
    model: "m",
    memory: { enabled: true, scope: "anything/goes" },
  });
  assert.equal(profile.memory.scope, "anything/goes");
});

// ---- profile loader -----------------------------------------------------------------------

test("GAP: a profile file whose JSON name differs from its filename loads", async () => {
  await withRoot(async (root) => {
    await writeFile(
      path.join(root, SYSTEM_DIR, "profiles", "alpha.json"),
      JSON.stringify({
        name: "beta",
        provider: "claude",
        model: "m",
        role: "r",
      }),
    );
    assert.equal((await loadProfile("alpha")).name, "beta");
  });
});

test("GAP: a path-like JSON name is accepted by validation (only the filename is checked)", async () => {
  await withRoot(async (root) => {
    await writeFile(
      path.join(root, SYSTEM_DIR, "profiles", "alpha.json"),
      JSON.stringify({
        name: "../../escape",
        provider: "claude",
        model: "m",
        role: "r",
      }),
    );
    assert.equal((await loadProfile("alpha")).name, "../../escape");
  });
});

test("GAP: malformed canonical JSON is swallowed and reported as a missing profile, not a parse error", async () => {
  await withRoot(async (root) => {
    await writeFile(
      path.join(root, SYSTEM_DIR, "profiles", "broken.json"),
      "{ not json",
    );
    await assert.rejects(loadProfile("broken"), (error) => {
      assert.doesNotMatch(String(error.message), /JSON/i);
      return true;
    });
  });
});

test("the legacy directory form (profile.json + instructions.md) still loads", async () => {
  await withRoot(async (root) => {
    const dir = path.join(root, SYSTEM_DIR, "profiles", "legacy");
    await mkdir(dir, { recursive: true });
    await writeFile(
      path.join(dir, "profile.json"),
      JSON.stringify({
        name: "legacy",
        provider: "claude",
        model: "m",
        role: "r",
      }),
    );
    await writeFile(path.join(dir, "instructions.md"), "be brief");
    const profile = await loadProfile("legacy");
    assert.equal(profile.instructions, "be brief");
  });
});

test("filename traversal and invalid characters are rejected before any read", async () => {
  await withRoot(async () => {
    for (const bad of ["../x", "a/b", "a.b", "", "a b"])
      await assert.rejects(loadProfile(bad), /Invalid profile name/);
  });
});

// ---- profile facts (memory) ---------------------------------------------------------------

test("facts live at SYSTEM_DIR/memory/profiles/<profile>.json, newest first, key-overwrite", async () => {
  await withRoot(async (root) => {
    await writeProfileFact("alpha", "a", "one");
    await writeProfileFact("alpha", "b", "two");
    await writeProfileFact("alpha", "a", "three");
    assert.equal(
      profileFactsFile("alpha"),
      path.join(root, SYSTEM_DIR, "memory", "profiles", "alpha.json"),
    );
    const facts = await readProfileFacts("alpha");
    assert.deepEqual(
      facts.map((fact) => [fact.key, fact.value]),
      [
        ["a", "three"],
        ["b", "two"],
      ],
    );
  });
});

test("facts are isolated per profile name and enforce key and size bounds", async () => {
  await withRoot(async () => {
    await writeProfileFact("alpha", "k", "alpha-value");
    await writeProfileFact("beta", "k", "beta-value");
    assert.equal((await readProfileFacts("alpha"))[0].value, "alpha-value");
    assert.equal((await readProfileFacts("beta"))[0].value, "beta-value");
    await assert.rejects(writeProfileFact("alpha", "bad key", "v"), /Fact key/);
    await assert.rejects(writeProfileFact("alpha", "k", "  "), /empty/);
    await assert.rejects(
      writeProfileFact("alpha", "k", "x".repeat(2_001)),
      /2000 bytes/,
    );
  });
});

test("facts are capped at 100 per profile", async () => {
  await withRoot(async () => {
    for (let index = 0; index < 105; index += 1)
      await writeProfileFact("alpha", `k${index}`, "v");
    assert.equal((await readProfileFacts("alpha")).length, 100);
  });
});

unixOnly("fact files are written with mode 0600", async () => {
  await withRoot(async () => {
    await writeProfileFact("alpha", "k", "v");
    const mode = (await stat(profileFactsFile("alpha"))).mode & 0o777;
    assert.equal(mode, 0o600);
  });
});

test("GAP: the profile name is not validated, so a traversal name writes outside memory/profiles", async () => {
  await withRoot(async (root) => {
    await writeProfileFact("../escape", "k", "v");
    const outside = path.join(root, SYSTEM_DIR, "memory", "escape.json");
    assert.match(await readFile(outside, "utf8"), /"key": "k"/);
    assert.ok(
      path
        .relative(
          path.join(root, SYSTEM_DIR, "memory", "profiles"),
          profileFactsFile("../escape"),
        )
        .startsWith(".."),
    );
  });
});

test("GAP: memory.scope does not influence where facts are stored", async () => {
  await withRoot(async () => {
    const scoped = validateProfile({
      name: "scoped",
      role: "r",
      provider: "claude",
      model: "m",
      memory: { enabled: false, scope: "disabled" },
    });
    // Storage is keyed by name alone; a disabled/other scope does not change the file.
    assert.equal(profileFactsFile(scoped.name), profileFactsFile("scoped"));
  });
});
