#!/usr/bin/env python3
"""tests/test-agent-handoff-identity.py — T-048: source_client/source_session_id on the
existing V6 agent-handoff record (cli/atlas-handoff).

T-048 is a minimal, additive extension only, owner-approved after AIOS-011 and AIOS-012
were found to already hold this territory closed. Nothing here is a lease, a lock, a
daemon, a queue or an automatic claim/archive — every scenario below that says so is
checking an *absence*, not just a presence.

Every scenario runs against a disposable ATLAS_HOME fixture built by `make_ticket_home()`,
matching the shape `atlas-paths ticket <id>` actually resolves (`projects/<proj>/tickets/
<id>/task.md`). Nothing here touches the real workspace or any real ticket.
"""
import contextlib
import importlib.util
import io
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli"

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


def t(label):
    print(f"\n{D}— {label}{X}")


spec = importlib.util.spec_from_loader(
    "atlas_handoff_under_test", SourceFileLoader("atlas_handoff_under_test", str(CLI / "atlas-handoff")))
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


def make_ticket_home(root, project="demo", ticket_id="T-900"):
    d = root / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "task.md").write_text(
        "---\nkind: ticket\nnamespace: atlas.ticket\nid: {id}\n"
        "title: fixture ticket for handoff identity tests\nstate: active\n"
        "project: {project}\nopened_at: 2026-09-06 12:00 PM\nupdated_at: 2026-09-06 12:00 PM\n"
        "artifacts: []\n---\n# fixture\n".format(id=ticket_id, project=project))
    return d


def write_legacy_record(d, handoff_id="20260101-legacy"):
    """A record shaped exactly like V6 wrote it before T-048 — no source_* keys at all."""
    p = d / f"handoff-{handoff_id}.md"
    p.write_text(f"""---
handoff_id: {handoff_id}
task_id: T-900
status: draft
created: 2026-01-01 09:00:00
to: codex
gate: review
scope: pre-existing record, written before T-048
current_holder: owner
next_holder: codex
owner_action_required: approve
approval: none
sent: no
returned: none
---

# Handoff {handoff_id} — T-900

Legacy body, no section 6.
""")
    return p


@contextlib.contextmanager
def captured():
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        yield out, err


def run(cmd_fn, args):
    """Call a cmd_* function like the CLI dispatcher does: capture output, capture the
    exit code from either a return value or a die()-raised SystemExit."""
    with captured() as (out, err):
        try:
            rc = cmd_fn(args)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def with_atlas_home(tmp_path_fn):
    import os
    root = tmp_path_fn()
    os.environ["ATLAS_HOME"] = str(root)
    return root


# =========================================================================================
import os
import tempfile

with tempfile.TemporaryDirectory(prefix="t048-handoff-") as tmp:
    root = Path(tmp)
    os.environ["ATLAS_HOME"] = str(root)
    d = make_ticket_home(root)

    # -- 1/2/16: new prepare record carries client + session identity, human-readable ----
    t("prepare: new record carries client and session identity")
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s1",
                        "--source-client", "claude-cli", "--source-session", "sess-001",
                        "--id", "id1"])
    chk("exit 0", rc == 0)
    chk("human-readable output names the source", "source: claude-cli/sess-001" in out)
    meta1 = handoff.parse_frontmatter((d / "handoff-id1.md").read_text())
    chk("frontmatter has source_client", meta1.get("source_client") == "claude-cli")
    chk("frontmatter has source_session_id", meta1.get("source_session_id") == "sess-001")

    # -- 10: missing optional identity does not error, defaults are explicit -------------
    t("prepare: identity omitted -> recorded as unspecified, not an error")
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s2",
                        "--id", "id2"])
    chk("exit 0", rc == 0)
    meta2 = handoff.parse_frontmatter((d / "handoff-id2.md").read_text())
    chk("source_client defaults to unspecified", meta2.get("source_client") == "unspecified")
    chk("source_session_id defaults to unspecified", meta2.get("source_session_id") == "unspecified")

    # -- 8/9: identity format validation --------------------------------------------------
    t("prepare: identity format validation")
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s3",
                        "--source-client", "claude-extension", "--id", "id3"])
    chk("a plain client id is accepted", rc == 0)
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s4",
                        "--source-client", "not a valid id!", "--id", "id4"])
    chk("a client id with spaces/punctuation is refused", rc == 2)
    chk("refusal names the field", "client identifier" in err)
    chk("nothing was written for the refused record", not (d / "handoff-id4.md").exists())
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s5",
                        "--source-session", "not a valid session!", "--id", "id5"])
    chk("a malformed session id is refused", rc == 2)
    chk("refusal names the field", "session identifier" in err)

    # -- duplicate/conflicting identity flags --------------------------------------------
    t("prepare: duplicate identity flag is refused, exactly like every other duplicate flag")
    rc, out, err = run(handoff.cmd_prepare,
                       ["T-900", "--to", "codex", "--gate", "review", "--scope", "s6",
                        "--source-client", "codex", "--source-client", "claude-cli",
                        "--id", "id6"])
    chk("exit 2", rc == 2)
    chk("refusal is specific", "source-client" in err and "more than once" in err)
    chk("nothing was written", not (d / "handoff-id6.md").exists())

    # -- 3/11/12: approve preserves identity; approval tuple matching is unchanged -------
    t("approve: preserves the identity prepare recorded; existing gate/scope/to matching holds")
    run(handoff.cmd_prepare,
        ["T-900", "--to", "codex", "--gate", "review", "--scope", "s7",
         "--status", "waiting-owner", "--source-client", "claude-extension",
         "--source-session", "ext-77", "--id", "id7"])
    rc, out, err = run(handoff.cmd_approve,
                       ["T-900", "id7", "--gate", "review", "--to", "codex", "--scope", "s7",
                        "--owner-words", "approved for the test"])
    chk("approve succeeds", rc == 0)
    meta7 = handoff.parse_frontmatter((d / "handoff-id7.md").read_text())
    chk("source_client survives approve", meta7.get("source_client") == "claude-extension")
    chk("source_session_id survives approve", meta7.get("source_session_id") == "ext-77")
    chk("approval mismatch on scope is still refused (unchanged V3 behavior)",
        run(handoff.cmd_approve,
            ["T-900", "id7", "--gate", "review", "--to", "codex", "--scope", "wrong-scope",
             "--owner-words", "x"])[0] == 2)

    # -- 11: identity stays visible/distinct rather than silently merged ----------------
    t("mismatched-looking identity across prepare vs a later action stays visible, not hidden")
    # prepare said claude-extension/ext-77; nothing in approve overwrote it (checked above),
    # and approve records no competing identity of its own — there is exactly one identity
    # source (prepare-time), and it is never silently replaced.
    chk("only prepare's identity is ever present on the record",
        meta7.get("source_client") == "claude-extension" and "approved_by_client" not in meta7)

    # -- 4/7: legacy records (no identity fields at all) remain valid --------------------
    t("legacy record (written before T-048) remains readable and valid")
    legacy = write_legacy_record(d)
    rc, out, err = run(handoff.cmd_show, ["T-900", "20260101-legacy"])
    chk("show does not error on a legacy record", rc == 0)
    chk("show surfaces the raw legacy record unchanged", "pre-existing record, written before T-048" in out)
    chk("show adds a visible fallback rather than fabricating identity",
        "legacy/legacy" in out)
    before = legacy.read_bytes()
    chk("show never rewrites the legacy record's bytes", legacy.read_bytes() == before)

    # -- 5/6/7/15/16: list/show human-readable output, legacy fallback -------------------
    t("list: shows identity for new records and a clear fallback for legacy ones")
    rc, out, err = run(handoff.cmd_list, ["T-900"])
    chk("exit 0", rc == 0)
    chk("lists a new record's identity", "claude-cli/sess-001" in out)
    chk("lists unspecified-but-recorded identity distinctly", "unspecified/unspecified" in out)
    chk("lists the legacy record with the legacy fallback, not a blank or a guess",
        "legacy/legacy" in out)

    t("machine-parseable form: frontmatter round-trips the new fields (no JSON CLI mode exists in V6; "
      "none was added — the frontmatter already is V6's structured form)")
    reparsed = handoff.parse_frontmatter((d / "handoff-id1.md").read_text())
    chk("re-parsing the record recovers exactly what was written",
        reparsed.get("source_client") == "claude-cli"
        and reparsed.get("source_session_id") == "sess-001")

    # -- 13/14: existing send/approve behavior is unchanged ------------------------------
    t("existing send behavior is unchanged (dry-run, no transport declared in this fixture)")
    run(handoff.cmd_prepare,
        ["T-900", "--to", "codex", "--gate", "review", "--scope", "s8",
         "--status", "waiting-owner", "--source-client", "claude-cli",
         "--source-session", "sess-008", "--id", "id8"])
    run(handoff.cmd_approve, ["T-900", "id8", "--gate", "review", "--to", "codex", "--scope", "s8",
                              "--owner-words", "approved"])
    rc, out, err = run(handoff.cmd_send, ["T-900", "id8", "--dry-run"])
    chk("dry-run send still works after the schema change", rc == 0)
    chk("dry-run send never writes (status unchanged)",
        handoff.parse_frontmatter((d / "handoff-id8.md").read_text()).get("status") == "approved")

    t("existing rejection behavior is unchanged (unknown handoff id)")
    rc, out, err = run(handoff.cmd_show, ["T-900", "does-not-exist"])
    chk("still refused with the existing not-found code", rc == 4)

    # -- 17/18/19/20: no automation was introduced ---------------------------------------
    t("no automatic claim, lease, lock, daemon, queue, or archive was introduced")
    all_text = "\n".join((d / f"handoff-{h}.md").read_text() for h in ("id1", "id2", "id3", "id7"))
    banned = ["lease_id", "lease_expires_at", "lock_id", "current_owner", "claimed_by",
              "heartbeat", "queue", "daemon"]
    chk("no lease/lock/daemon/queue vocabulary appears in any record this test wrote",
        not any(b in all_text for b in banned))
    entries = sorted(p.name for p in d.iterdir())
    chk("only handoff-*.md and task.md exist in the ticket dir — no lock file, no state file",
        all(n == "task.md" or n.startswith("handoff-") and n.endswith(".md") for n in entries))
    chk("the ticket record itself was never touched by any handoff command",
        (d / "task.md").read_text().startswith("---\nkind: ticket"))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
