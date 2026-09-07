#!/usr/bin/env python3
"""Contract checks for the read-only Markdown knowledge index."""

import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path


CLI = Path(__file__).resolve().parents[1] / "cli" / "ai-os-knowledge-index"


def run(source, db, *extra):
    result = subprocess.run(
        [str(CLI), "--source-dir", str(source), "--db", str(db), *extra],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "notes"
        db = Path(tmp) / "index.sqlite3"
        root.mkdir()
        first = root / "first.md"
        second = root / "second.md"
        first.write_text("---\ntags: [alpha]\nproject_id: ai-os\nticket_id: T-056\n---\n#alpha [[second]]\n", encoding="utf-8")
        second.write_text("# Second\n", encoding="utf-8")

        source_before = first.read_bytes(), second.read_bytes()
        assert run(root, db)["notes_created"] == 2
        assert run(root, db)["notes_unchanged"] == 2
        first.write_text("---\nproject_id: ai-os\nticket_id: T-056\n---\n#alpha #changed [[second]]\n", encoding="utf-8")
        changed_source = first.read_bytes()
        assert run(root, db)["notes_updated"] == 1
        second.unlink()
        assert run(root, db)["notes_removed"] == 1

        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT tag FROM tags WHERE path = 'first.md' AND tag = 'changed'").fetchone()
            assert conn.execute("SELECT source_path FROM backlinks WHERE target = 'second' AND source_path = 'first.md'").fetchone()
            assert conn.execute("SELECT path FROM notes WHERE path = 'second.md' AND removed = 1").fetchone()
            assert conn.execute("SELECT path FROM note_events WHERE event = 'removed'").fetchone()
            assert conn.execute("SELECT COUNT(*) FROM index_runs").fetchone()[0] == 4

        assert first.read_bytes() == changed_source
        assert source_before[1] == b"# Second\n"
        assert run(root, db, "--rebuild")["notes_created"] == 1

        search = run(root, db, "--search", "T-056")
        assert search["mode"] == "search" and search["notes"][0]["path"] == "first.md"
        assert search["notes"][0]["references"]

        graph = run(root, db, "--graph", "second")
        assert graph["mode"] == "graph" and "first.md" in graph["linked_from"]

        sensitive = root / "secret-note.md"
        sensitive.write_text("#secret [[first]]\n", encoding="utf-8")
        run(root, db)
        assert run(root, db, "--search", "secret")["notes"] == []

    print("5/5 knowledge-index checks passed")


if __name__ == "__main__":
    main()
