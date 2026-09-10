import assert from "node:assert/strict";
import test from "node:test";
import { buildProviderInvocation } from "../dist/infrastructure/providers/providers.js";
import { validateProfile } from "../dist/domain/profiles/profile-validator.js";

test("builds the Claude CLI stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "claude", prompt: "hello", cwd: "/tmp",
  }), {
    command: "claude",
    args: ["-p", "hello", "--verbose", "--output-format", "stream-json"],
  });
});

test("builds the Codex JSON contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "codex", prompt: "hello", cwd: "/tmp",
  }), {
    command: "codex",
    args: ["exec", "--json", "hello"],
  });
});

test("builds the Gemini stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "gemini", prompt: "hello", cwd: "/tmp",
  }), {
    command: "gemini",
    args: ["--prompt", "hello", "--output-format", "stream-json"],
  });
});

test("accepts Gemini as a profile provider", () => {
  assert.equal(validateProfile({
    name: "gemini", provider: "gemini", model: "flash", role: "assistant",
  }).provider, "gemini");
});

test("adds Claude resume ids without changing the CLI stream contract", () => {
  assert.deepEqual(buildProviderInvocation({
    provider: "claude", prompt: "continue", cwd: "/tmp", resumeId: "session-1",
  }).args, ["--resume", "session-1", "-p", "continue", "--verbose", "--output-format", "stream-json"]);
});
