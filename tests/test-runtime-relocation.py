#!/usr/bin/env python3
"""Persistent sync data belongs to the private workspace, not the runtime layer.

V0.1.5 moved ai-sync's state record and its pre-overwrite backups out of
~/.ai/sync/{state,backups} and into $AI_OS_HOME/internal/runtime/{state,backups}. These tests
exercise that relocation against a throwaway HOME — nothing here reads or writes the
real workspace, the real runtime, or any real client configuration.

The migration's hard promise is that it never picks a winner. Where both sides hold the
same bytes the legacy copy is redundant and goes; where they differ it stops and says so.
Most of what follows is about that second case, because silently choosing is how a user's
backups disappear.
"""
import importlib.util, os, shutil, sys, tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# The canonical engine, since step 12a. ~/.ai/bin/ai-sync is a passthrough shim that
# execs this file, so importing it as a module would exec instead of load.
SYNC = REPO / "cli" / "ai-sync"

G, R, D, X = "\033[32m", "\033[31m", "\033[2m", "\033[0m"
if not sys.stdout.isatty():
    G = R = D = X = ""
passed = failed = 0


def chk(desc, ok):
    global passed, failed
    if ok:
        print(f"  {G}PASS{X} {desc}"); passed += 1
    else:
        print(f"  {R}FAIL{X} {desc}"); failed += 1


def load_sync(home: Path, ws: Path):
    """Import ai-sync with HOME and AI_OS_HOME pointed at a scratch tree.

    Paths are module-level constants computed at import, so the environment has to be in
    place first and the module has to be loaded fresh for every scenario.
    """
    os.environ["HOME"] = str(home)
    os.environ["AI_OS_HOME"] = str(ws)
    os.environ["AI_OS_REPO"] = str(REPO)
    for mod in [m for m in sys.modules if m.startswith("aios_sync")]:
        del sys.modules[mod]
    name = f"aios_sync_{id(home)}"
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(SYNC)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def scratch(tmp, label, legacy_state=None, legacy_backups=None, new_state=None,
            new_backups=None):
    """Build one throwaway HOME/workspace pair and return (module, home, ws)."""
    home = tmp / label / "home"
    ws = tmp / label / "ws"
    (home / ".ai" / "sync").mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)
    if legacy_state is not None:
        d = home / ".ai" / "sync" / "state"; d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(legacy_state)
    for tag, files in (legacy_backups or {}).items():
        d = home / ".ai" / "sync" / "backups" / tag; d.mkdir(parents=True, exist_ok=True)
        for n, c in files.items():
            (d / n).write_text(c)
    if new_state is not None:
        d = ws / "internal" / "runtime" / "state"; d.mkdir(parents=True, exist_ok=True)
        (d / "state.json").write_text(new_state)
    for tag, files in (new_backups or {}).items():
        d = ws / "internal" / "runtime" / "backups" / tag; d.mkdir(parents=True, exist_ok=True)
        for n, c in files.items():
            (d / n).write_text(c)
    return load_sync(home, ws), home, ws


def main():
    real_home = os.environ.get("HOME")
    tmp = Path(tempfile.mkdtemp(prefix="ai-os-relocation."))
    try:
        # --- 1, 2, 11: a fresh installation writes only to the new canonical location ---
        print(f"\n{D}— fresh installation uses the private workspace{X}")
        m, home, ws = scratch(tmp, "fresh")
        chk("state resolves under AI_OS_HOME/internal/runtime",
            m.STATE == ws / "internal" / "runtime" / "state" / "state.json")
        chk("backups resolve under AI_OS_HOME/internal/runtime",
            m.BACKUPS == ws / "internal" / "runtime" / "backups")
        chk("a custom AI_OS_HOME is honoured, not $HOME/.ai-os",
            str(ws) in str(m.STATE) and ".ai-os" not in str(m.STATE))
        m.migrate_runtime()
        m.save_state({"version": 1, "clients": {}, "history": []})
        chk("save_state wrote to the new location", m.STATE.exists())
        chk("   ...and created nothing under the runtime layer",
            not (home / ".ai" / "sync" / "state").exists())
        src = home / "a-file.md"; src.write_text("original")
        m.backup(src, "20260101-000000")
        chk("backup() wrote to the new location",
            (m.BACKUPS / "20260101-000000").is_dir())
        chk("   ...and created nothing under the runtime layer",
            not (home / ".ai" / "sync" / "backups").exists())

        # --- 3, 4, 5: legacy data migrates, byte for byte ---------------------------
        print(f"\n{D}— existing legacy data migrates without loss{X}")
        payload = '{"version": 1, "clients": {"x": {"rules_hash": "abc"}}}'
        m, home, ws = scratch(tmp, "legacy",
                              legacy_state=payload,
                              legacy_backups={"20260830-120508": {"a__CLAUDE.md": "one",
                                                                  "b__AGENTS.md": "two"},
                                              "pre-sync-originals": {"k.md": "three"}})
        rc = m.migrate_runtime()
        chk("migration succeeds", rc == 0)
        chk("state moved", m.STATE.exists())
        chk("state is byte-identical", m.STATE.read_text() == payload)
        chk("a timestamped backup tag moved",
            (m.BACKUPS / "20260830-120508" / "a__CLAUDE.md").exists())
        chk("its contents are byte-identical",
            (m.BACKUPS / "20260830-120508" / "a__CLAUDE.md").read_text() == "one"
            and (m.BACKUPS / "20260830-120508" / "b__AGENTS.md").read_text() == "two")
        chk("a non-timestamped archive moves too, not just sync tags",
            (m.BACKUPS / "pre-sync-originals" / "k.md").read_text() == "three")

        # --- 7, 8: the old locations are gone and stay gone --------------------------
        print(f"\n{D}— the runtime layer no longer owns persistent data{X}")
        chk("legacy state directory removed", not (home / ".ai/sync/state").exists())
        chk("legacy backups directory removed", not (home / ".ai/sync/backups").exists())
        m.save_state(m.load_state())
        m.backup(home / "a2.md", "20260102-000000")
        (home / "a2.md").write_text("later"); m.backup(home / "a2.md", "20260102-000000")
        chk("further writes do not recreate ~/.ai/sync/state",
            not (home / ".ai/sync/state").exists())
        chk("further writes do not recreate ~/.ai/sync/backups",
            not (home / ".ai/sync/backups").exists())

        # --- 6: idempotence ----------------------------------------------------------
        print(f"\n{D}— the migration is idempotent{X}")
        before = sorted(p.relative_to(ws) for p in ws.rglob("*") if p.is_file())
        chk("a second run succeeds", m.migrate_runtime() == 0)
        chk("a third run succeeds", m.migrate_runtime() == 0)
        after = sorted(p.relative_to(ws) for p in ws.rglob("*") if p.is_file())
        chk("   ...and changes nothing", before == after)

        # --- 9: rollback still works from the relocated backups ----------------------
        print(f"\n{D}— rollback still works from the relocated backups{X}")
        m, home, ws = scratch(tmp, "rollback",
                              legacy_backups={"20260830-174332": {"x__CLAUDE.md": "backed-up"}})
        m.migrate_runtime()
        import re as _re
        tags = sorted((d.name for d in m.BACKUPS.iterdir()
                       if d.is_dir() and _re.fullmatch(r"\d{8}-\d{6}", d.name)), reverse=True)
        chk("a rollback target is discoverable after the move", tags == ["20260830-174332"])
        chk("   ...and its restorable payload survived",
            (m.BACKUPS / tags[0] / "x__CLAUDE.md").read_text() == "backed-up")

        # --- 10: determinism ---------------------------------------------------------
        print(f"\n{D}— repeated operation stays a no-op{X}")
        m, home, ws = scratch(tmp, "determinism", legacy_state=payload)
        m.migrate_runtime()
        first = m.STATE.read_bytes()
        m.migrate_runtime(); m.migrate_runtime()
        chk("state bytes unchanged across repeated runs", m.STATE.read_bytes() == first)
        chk("load_state round-trips the migrated file",
            m.load_state()["clients"]["x"]["rules_hash"] == "abc")

        # --- failure cases: refuse rather than destroy -------------------------------
        print(f"\n{D}— conflicts stop the migration instead of choosing a winner{X}")
        m, home, ws = scratch(tmp, "conflict-state",
                              legacy_state='{"version": 1, "clients": {"old": {}}}',
                              new_state='{"version": 1, "clients": {"new": {}}}')
        rc = m.migrate_runtime()
        chk("conflicting state exits non-zero", rc != 0)
        chk("   ...the legacy copy is still there", (home / ".ai/sync/state/state.json").exists())
        chk("   ...and the destination was NOT overwritten",
            "new" in m.STATE.read_text())

        m, home, ws = scratch(tmp, "conflict-backup",
                              legacy_backups={"20260830-120508": {"a__CLAUDE.md": "legacy"}},
                              new_backups={"20260830-120508": {"a__CLAUDE.md": "different"}})
        rc = m.migrate_runtime()
        chk("a backup tag differing on both sides exits non-zero", rc != 0)
        chk("   ...neither side was destroyed",
            (home / ".ai/sync/backups/20260830-120508/a__CLAUDE.md").read_text() == "legacy"
            and (m.BACKUPS / "20260830-120508" / "a__CLAUDE.md").read_text() == "different")

        print(f"\n{D}— already-migrated and empty installations are handled cleanly{X}")
        m, home, ws = scratch(tmp, "already", new_state=payload)
        chk("nothing legacy, nothing to do", m.migrate_runtime() == 0)
        chk("   ...the existing state is untouched", m.STATE.read_text() == payload)

        m, home, ws = scratch(tmp, "duplicate", legacy_state=payload, new_state=payload)
        chk("identical copies on both sides succeed", m.migrate_runtime() == 0)
        chk("   ...the redundant legacy copy is dropped",
            not (home / ".ai/sync/state/state.json").exists())
        chk("   ...and the canonical copy survives intact", m.STATE.read_text() == payload)

        m, home, ws = scratch(tmp, "empty")
        (home / ".ai" / "sync" / "backups").mkdir(parents=True, exist_ok=True)
        chk("an empty legacy backups directory succeeds", m.migrate_runtime() == 0)

        m, home, ws = scratch(tmp, "no-workspace", legacy_state=payload)
        shutil.rmtree(ws)
        chk("a missing workspace is created, not fatal", m.migrate_runtime() == 0)
        chk("   ...and the data landed there", m.STATE.read_text() == payload)

        # --- 12, 13: nothing machine-specific, nothing client-specific ---------------
        print(f"\n{D}— the relocation names no machine and no client{X}")
        src_text = SYNC.read_text()
        start = src_text.index("def migrate_runtime")
        body = src_text[start:src_text.index("\ndef load_state")]
        chk("no client is named in the migration",
            not any(c in body.lower() for c in
                    ("claude", "codex", "gemini", "cursor", "opencode")))
        chk("no machine-specific path is introduced",
            not any(s in body for s in ("/Users/", "Documents", "Projects", "Developer")))
        chk("the destination comes from AI_OS_HOME, never a literal",
            "AI_OS_HOME" in src_text.split("def migrate_runtime")[0]
            and 'RUNTIME = private_path_or_die("runtime")' in src_text)
    finally:
        if real_home:
            os.environ["HOME"] = real_home
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n  {passed}/{passed + failed} passed" +
          (f", {R}{failed} failed{X}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
