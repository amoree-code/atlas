// Tests sandbox the workspace through OCEAN_*; clear any OCEAN_* inherited from the shell so it
// cannot leak into them. The engine still falls back to the legacy ATLAS_* names, so clear those too.
for (const name of Object.keys(process.env)) {
  if (name.startsWith("OCEAN_") || name.startsWith("ATLAS_"))
    delete process.env[name];
}
