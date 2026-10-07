import { mkdtempSync, realpathSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Tests sandbox the workspace through OCEAN_*; clear any OCEAN_* inherited from the shell so it
// cannot leak into them. The engine still falls back to the legacy ATLAS_* names, so clear those too.
// The opt-in gates below are switches the developer sets on purpose, not workspace state: keep them.
const GATES = [
  "LIVE_PROVIDER_TESTS",
  "LIVE_EMBEDDER_TESTS",
  "BROWSER_INTEGRATION",
];
const keep = new Set(
  GATES.flatMap((gate) => [`OCEAN_${gate}`, `ATLAS_${gate}`]),
);
for (const name of Object.keys(process.env)) {
  if (keep.has(name)) continue;
  if (name.startsWith("OCEAN_") || name.startsWith("ATLAS_"))
    delete process.env[name];
}

// Every test process starts on an empty workspace root of its own. The engine picks the layout
// (flat or brain/-nested, T-243) from the root it loads with, and a test that never sets OCEAN_ROOT
// would otherwise write into the real workspace next to the checkout.
const sandbox = realpathSync(
  mkdtempSync(path.join(tmpdir(), "ocean-test-root-")),
);
process.env.OCEAN_ROOT = sandbox;
process.on("exit", () => rmSync(sandbox, { recursive: true, force: true }));
