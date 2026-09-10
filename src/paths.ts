import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDirectory = path.dirname(fileURLToPath(import.meta.url));

// This module always lives one directory below the engine package root, whether it
// runs compiled from dist/ or directly from src/ under tsx.
const engineDirectory = path.resolve(moduleDirectory, "..");

// The default runtime data root is the private workspace sibling of engine/, e.g.
// ~/atlas/engine (this package) next to ~/atlas/personal, ~/atlas/sessions, etc.
const defaultAtlasRoot = path.resolve(engineDirectory, "..");

export function engineRoot(): string {
  return engineDirectory;
}

export function enginePath(...parts: string[]): string {
  return path.join(engineRoot(), ...parts);
}

export function atlasRoot(): string {
  return process.env.ATLAS_ROOT ? path.resolve(process.env.ATLAS_ROOT) : defaultAtlasRoot;
}

export function atlasPath(...parts: string[]): string {
  return path.join(atlasRoot(), ...parts);
}

// Private application state (config, profiles, sessions, logs, cache, and integrations)
// lives at the workspace root, separate from the public engine and user data trees.
export function atlasStatePath(...parts: string[]): string {
  return atlasPath(...parts);
}
