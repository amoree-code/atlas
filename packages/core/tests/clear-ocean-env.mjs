// Tests sandbox the workspace through ATLAS_*; an inherited OCEAN_* would win over it.
for (const name of Object.keys(process.env)) {
  if (name.startsWith("OCEAN_")) delete process.env[name];
}
