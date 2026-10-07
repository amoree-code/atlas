import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
  lstatSync,
  mkdirSync,
  mkdtempSync,
  readdirSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

// The layout is read once per process from the root it loads with, so every case runs the CLI in
// a fresh process against a fixture HOME whose workspace root is HOME/ocean.
function fixture(files) {
  const home = mkdtempSync(path.join(os.tmpdir(), "ocean-layout-plan-"));
  const root = path.join(home, "ocean");
  for (const [file, content] of Object.entries(files)) {
    const target = path.join(home, file.replaceAll("<root>", root));
    mkdirSync(path.dirname(target), { recursive: true });
    if (content === null) mkdirSync(target, { recursive: true });
    else writeFileSync(target, content.replaceAll("<root>", root));
  }
  return { home, root };
}

function plan({ home, root }, args = ["plan"]) {
  const result = spawnSync(
    process.execPath,
    [path.resolve("dist/main.js"), "layout", ...args],
    {
      env: { PATH: process.env.PATH, HOME: home, OCEAN_ROOT: root },
      encoding: "utf8",
    },
  );
  return result;
}

function snapshot(directory) {
  const seen = [];
  const walk = (current) => {
    for (const name of readdirSync(current)) {
      const target = path.join(current, name);
      const info = lstatSync(target);
      seen.push(`${target}:${info.size}:${info.mtimeMs}`);
      if (info.isDirectory()) walk(target);
    }
  };
  walk(directory);
  return seen.sort();
}

const NESTED = {
  "ocean/brain/04-projects/atlas/tasks/T-1/task.md": "task",
  "ocean/brain/charter/core.md":
    "policies live in `~/ocean/brain/charter/policies`\n",
  "ocean/brain/README.md": "brain readme",
  "ocean/brain/.DS_Store": "junk",
  "ocean/README.md": "root readme",
  "ocean/.gitignore": "/kernel/\nbrain/.index/\n.env\n",
  "ocean/kernel/bridge/sessions/sessions.sqlite": "db!",
  "ocean/kernel/bridge/sessions/log.txt":
    "<root>/kernel/bridge is data, not a pointer",
  "ocean/kernel/bridge/runtime/shims/claude":
    'exec "$HOME/ocean/kernel/bridge/runtime/run" "$@"\n',
  "ocean/user/01-daily": null,
  ".claude/CLAUDE.md": "@~/ocean/brain/charter/core.md\n",
  ".claude/settings.json":
    '{"a":"<root>/kernel/bridge/hooks/x","b":"<root>/kernel/bridge/hooks/y"}',
  // biome-ignore lint/suspicious/noTemplateCurlyInString: the literal ${HOME} spelling is what the scan must find
  ".claude/skills/demo/SKILL.md": "see ${HOME}/ocean/brain/04-projects\n",
  ".zshrc": "export PATH=~/ocean-old/brain/:$PATH\n",
  ".zprofile": "binary\0 ~/ocean/brain/x",
};

test("layout plan describes the move of a nested root without writing anything", () => {
  const where = fixture(NESTED);
  try {
    symlinkSync(
      "runtime",
      path.join(where.root, "kernel", "bridge", "current"),
    );
    const before = snapshot(where.home);
    const result = plan(where);
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(snapshot(where.home), before, "plan wrote to disk");
    const report = JSON.parse(result.stdout);
    assert.deepEqual(report.layout, { records: "nested", bridge: "nested" });
    assert.deepEqual(
      report.moves.map(({ from, to, files, symlinks }) => [
        from,
        to,
        files,
        symlinks,
      ]),
      [
        ["brain/04-projects", "04-projects", 1, 0],
        ["brain/README.md", "README.md", 1, 0],
        ["brain/charter", "charter", 1, 0],
        ["kernel/bridge", "bridge", 3, 1],
      ],
    );
    assert.deepEqual(report.collisions, [
      { from: "brain/README.md", to: "README.md" },
    ]);
    assert.equal(report.ready, false, "a collision blocks apply");
    assert.deepEqual(report.strays, ["user"]);
    assert.deepEqual(report.gitignore, [
      { from: "brain/.index/", to: ".index/" },
      { from: null, to: "/bridge/" },
    ]);
    const pointers = Object.fromEntries(
      report.pointers.map(({ file, references }) => [
        path.relative(where.home, file),
        references,
      ]),
    );
    assert.deepEqual(pointers, {
      ".claude/CLAUDE.md": 1,
      ".claude/settings.json": 2,
      ".claude/skills/demo/SKILL.md": 1,
      "ocean/kernel/bridge/runtime/shims/claude": 1,
      "ocean/brain/charter/core.md": 1,
    });
  } finally {
    rmSync(where.home, { recursive: true, force: true });
  }
});

test("without a collision the nested root is ready to apply", () => {
  const { "ocean/README.md": _, ...files } = NESTED;
  const where = fixture(files);
  try {
    const report = JSON.parse(plan(where).stdout);
    assert.deepEqual(report.collisions, []);
    assert.equal(report.ready, true);
  } finally {
    rmSync(where.home, { recursive: true, force: true });
  }
});

test("a root already on the flat layout has nothing to move", () => {
  const where = fixture({
    "ocean/04-projects/ocean/tasks/T-1/task.md": "task",
    "ocean/charter/core.md": "core",
    "ocean/bridge/sessions/sessions.sqlite": "db",
    "ocean/.gitignore": ".index/\n/bridge/\n",
  });
  try {
    const report = JSON.parse(plan(where).stdout);
    assert.deepEqual(report.layout, { records: "flat", bridge: "flat" });
    assert.deepEqual(report.moves, []);
    assert.deepEqual(report.gitignore, []);
    assert.deepEqual(report.strays, []);
    assert.equal(report.ready, false);
  } finally {
    rmSync(where.home, { recursive: true, force: true });
  }
});

test("layout rejects an unknown action", () => {
  const where = fixture({});
  try {
    const result = plan(where, ["move-it"]);
    assert.equal(result.status, 1);
    assert.match(result.stderr, /Usage: ocean layout plan/);
  } finally {
    rmSync(where.home, { recursive: true, force: true });
  }
});
