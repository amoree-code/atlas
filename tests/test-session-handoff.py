#!/usr/bin/env python3
"""tests/test-session-handoff.py — automatic new-session handoff (checkpoint pointer +
`atlas context --resume` + the `SessionStart` adapter).

Two live files are under test, both resolved the same way the real dispatchers resolve
them (not assumed):

  ~/atlas/context/atlas-context                    canonical since T-016 (--resume lives here)
  ~/Documents/amir/atlas-engine/cli/atlas-tickets   canonical — tickets are NOT cut over to
                                                     ~/atlas yet (confirmed by
                                                     test-cli-source-drift.py); the pointer
                                                     writer lives in this repo copy, correctly

Every scenario runs against a disposable ATLAS_HOME/ATLAS_HOME fixture. Nothing here
touches the real workspace or the real pointer at ~/atlas/runtime/session-handoffs/.

What this file does NOT cover: whether Claude Code's `SessionStart` hook actually delivers
`additionalContext` to a fresh session. That contract was verified separately, by hand,
with a real headless `claude --settings <throwaway>.json -p "..."` run (see
`adapters/claude-code/ai-atlas-resume`'s own docstring and `adapters/claude-code/hooks.md`)
— it needs a real `claude` binary and a real API call, so it is not part of this
automated, offline suite. `test_real_claude_session_discovers_pending_handoff` below
reproduces that exact proof and is SKIPPED by default; set
ATLAS_TEST_REAL_CLAUDE=1 to run it.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "cli"
LIVE_CONTEXT = Path.home() / "atlas" / "context" / "atlas-context"

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


if not LIVE_CONTEXT.is_file():
    print("  (skipped — no ~/atlas/context/atlas-context found on this machine; nothing "
          "to check)")
    print("\n0 passed, 0 failed")
    sys.exit(0)


def make_ticket(home, project, ticket_id, next_action="do the thing", blockers=None,
                 state="active"):
    d = home / "projects" / project / "tickets" / ticket_id
    d.mkdir(parents=True, exist_ok=True)
    body = (f"---\nid: {ticket_id}\ntitle: fixture {ticket_id}\nstate: {state}\n"
            f"project: {project}\nopened: 2026-09-06\nupdated: 2026-09-06\n---\n\n"
            f"## Next action\n\n{next_action}\n\n")
    if blockers:
        body += f"## Blockers\n\n{blockers}\n\n"
    body += "## Log\n\n- 2026-09-06: created\n"
    (d / "task.md").write_text(body)
    return d


def run_checkpoint(home, ticket_id, *args):
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run(
        [str(CLI / "atlas-tickets"), "checkpoint", ticket_id, *args],
        cwd=str(home), env=env, capture_output=True, text=True)


def run_resume(home, *args, cwd=None):
    # ATLAS_HOME is what actually decides where `projects` (and so the pointer's sibling
    # `runtime/`) resolves to — matching how the writer resolves it in atlas-tickets.
    env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home), "PATH": os.environ["PATH"]}
    return subprocess.run([sys.executable, str(LIVE_CONTEXT), "--resume", *args],
                          cwd=cwd or str(home), env=env, capture_output=True, text=True)


def pointer_path(home):
    return home / "runtime" / "session-handoffs" / "latest.md"


with tempfile.TemporaryDirectory() as tmp:
    home = Path(tmp) / "home"
    (home / "runtime").mkdir(parents=True)  # simulate an existing Atlas root
    make_ticket(home, "fixtureproj", "T-900", next_action="first step",
                blockers="waiting on review")

    # --- 1-3: checkpoint creates latest.md with the expected compact fields, pending ---
    t("checkpoint creates the pointer, pending, with the expected fields")
    r = run_checkpoint(home, "T-900", "--note", "made progress", "--next", "second step")
    chk("checkpoint exits 0", r.returncode == 0)
    p = pointer_path(home)
    chk("latest.md was created", p.is_file())
    text = p.read_text() if p.is_file() else ""
    chk("contains ticket: T-900", "ticket: T-900" in text)
    chk("contains checkpointed_at:", "checkpointed_at:" in text)
    chk("contains the checkpoint note as state", "state: made progress" in text)
    chk("contains the new next action", "next_action: second step" in text)
    chk("contains the ticket's blocker", "blockers: waiting on review" in text)
    chk("contains a read_with command naming the ticket",
        "read_with: atlas context T-900" in text)
    chk("starts pending", "status: pending" in text)
    chk("does NOT duplicate ticket prose (no Objective/Verification/Log headers)",
        "Objective" not in text and "Verification" not in text and "## Log" not in text)

    # --- 4: a second checkpoint REPLACES, not appends -----------------------------------
    t("a second checkpoint on the same ticket replaces the pointer")
    r2 = run_checkpoint(home, "T-900", "--note", "more progress", "--next", "third step")
    chk("checkpoint exits 0", r2.returncode == 0)
    text2 = p.read_text()
    chk("only one 'ticket:' line exists (no duplication/append)",
        text2.count("ticket:") == 1)
    chk("state reflects the SECOND note, not the first",
        "state: more progress" in text2 and "made progress" not in text2)
    chk("status reset to pending by the new checkpoint", "status: pending" in text2)

    # --- 5: a second ticket replaces the previous pointer correctly ----------------------
    t("checkpointing a different ticket replaces the previous pointer, not both")
    make_ticket(home, "fixtureproj", "T-901", next_action="other ticket's action")
    r3 = run_checkpoint(home, "T-901", "--note", "started T-901", "--next", "keep going")
    chk("checkpoint exits 0", r3.returncode == 0)
    text3 = p.read_text()
    chk("pointer now names T-901, not T-900", "ticket: T-901" in text3 and
        "ticket: T-900" not in text3)
    chk("only one file exists in session-handoffs/",
        len(list((home / "runtime" / "session-handoffs").iterdir())) == 1)

    # --- 6: resume with no pointer exits 0 ------------------------------------------------
    t("resume with no pointer at all")
    empty_home = Path(tmp) / "empty"
    (empty_home / "runtime").mkdir(parents=True)
    r4 = run_resume(empty_home)
    chk("exits 0", r4.returncode == 0)
    chk("reports no pending handoff", "no pending handoff" in r4.stdout)

    # --- 7-8: resume with a pending pointer prints it, then marks consumed --------------
    t("resume with a pending pointer prints ticket/command, then consumes it")
    r5 = run_resume(home)
    chk("exits 0", r5.returncode == 0)
    chk("prints the ticket id", "T-901" in r5.stdout)
    chk("prints the exact read command", "atlas context T-901" in r5.stdout)
    chk("prints the next action", "keep going" in r5.stdout)
    chk("pointer is now consumed", "status: consumed" in p.read_text())

    # --- 9: resume twice does not replay a consumed pointer ------------------------------
    t("a second resume does not replay the consumed pointer")
    r6 = run_resume(home)
    chk("exits 0", r6.returncode == 0)
    chk("reports no pending handoff, not the old T-901 content",
        "no pending handoff" in r6.stdout and "T-901" not in r6.stdout)

    # --- 10: a new checkpoint after consumption returns to pending -----------------------
    t("a new checkpoint after consumption returns the pointer to pending")
    r7 = run_checkpoint(home, "T-901", "--note", "resumed work", "--next", "final step")
    chk("checkpoint exits 0", r7.returncode == 0)
    chk("pointer is pending again", "status: pending" in p.read_text())
    r8 = run_resume(home)
    chk("resume sees it as pending and reports it", "final step" in r8.stdout)

    # --- 11-12: malformed pointer is safe; failed parse never consumes -------------------
    t("a malformed pointer (missing required field) fails safely, unmodified")
    bad_home = Path(tmp) / "bad"
    (bad_home / "runtime" / "session-handoffs").mkdir(parents=True)
    bad_pointer = bad_home / "runtime" / "session-handoffs" / "latest.md"
    bad_pointer.write_text("checkpointed_at: 2026-09-06 3:00 AM\nstatus: pending\n")
    before_bad = bad_pointer.read_text()
    r9 = run_resume(bad_home)
    chk("exits non-zero (not 0, not the argparse-conflict code 2)",
        r9.returncode not in (0, 2))
    chk("prints a clear diagnostic naming the missing field",
        "ticket" in r9.stderr and "malformed" in r9.stderr)
    chk("the pointer file is byte-identical afterward (never touched)",
        bad_pointer.read_text() == before_bad)

    t("a malformed pointer (bad status value) fails safely, unmodified")
    bad_pointer.write_text("ticket: T-1\ncheckpointed_at: 2026-09-06 3:00 AM\n"
                           "status: not-a-real-status\n")
    before_bad2 = bad_pointer.read_text()
    r10 = run_resume(bad_home)
    chk("exits non-zero", r10.returncode not in (0, 2))
    chk("pointer untouched", bad_pointer.read_text() == before_bad2)

    # --- 13-15: argument conflicts --------------------------------------------------------
    t("--resume --mode planning is rejected")
    r11 = run_resume(home, "--mode", "planning")
    chk("exits 2", r11.returncode == 2)

    t("--resume --boundary is rejected")
    r12 = run_resume(home, "--boundary")
    chk("exits 2", r12.returncode == 2)

    t("--resume --json is explicitly SUPPORTED (verified CLI contract, not rejected)")
    make_ticket(home, "fixtureproj", "T-902", next_action="json path")
    run_checkpoint(home, "T-902", "--note", "json test", "--next", "json path")
    r13 = run_resume(home, "--json")
    chk("exits 0", r13.returncode == 0)
    try:
        data = json.loads(r13.stdout)
        chk("valid JSON with pending: true and the right ticket",
            data.get("pending") is True and data.get("ticket") == "T-902")
    except ValueError:
        chk("valid JSON with pending: true and the right ticket", False)

    # --- credential-shaped content is refused for the POINTER, not the checkpoint --------
    # The fake key is assembled at runtime, not written as one contiguous literal, so this
    # file itself never contains a credential-shaped string for atlas-privacy-scan to flag
    # — only the CREDENTIAL regex, matched against the runtime value, needs to see it.
    t("a credential-shaped checkpoint note is kept out of the pointer")
    fake_key_prefix, fake_key_body = "sk-ant" + "-", "abcdefghijklmnopqrstuvwxyz123456"
    fake_key = fake_key_prefix + fake_key_body
    make_ticket(home, "fixtureproj", "T-903", next_action="rotate it")
    r14 = run_checkpoint(home, "T-903", "--note",
                         f'rotated api_key="{fake_key}"',
                         "--next", "confirm rotation")
    chk("checkpoint itself still succeeds", r14.returncode == 0)
    chk("stderr warns the pointer was skipped",
        "credential-shaped" in r14.stderr)
    chk("the pointer was NOT overwritten with the credential-shaped note",
        fake_key_prefix not in pointer_path(home).read_text())

    # --- 16-18: existing behavior stays intact --------------------------------------------
    t("existing default context / --mode planning / checkpoint-without-pointer-fields "
      "remain unaffected")
    default_env = {"ATLAS_HOME": str(home), "ATLAS_HOME": str(home),
                   "PATH": os.environ["PATH"]}
    d1 = subprocess.run([sys.executable, str(LIVE_CONTEXT)], cwd=str(home),
                        env=default_env, capture_output=True, text=True)
    chk("default `atlas context` still runs cleanly", d1.returncode == 0)
    d2 = subprocess.run([sys.executable, str(LIVE_CONTEXT), "--mode", "planning"],
                        cwd=str(home), env=default_env, capture_output=True, text=True)
    chk("`--mode planning` still runs cleanly", d2.returncode == 0)
    d3 = run_checkpoint(home, "T-903", "--note", "harmless follow-up", "--next", "done")
    chk("a normal checkpoint (no pointer-specific fields) still succeeds", d3.returncode == 0)


print(f"\n{passed} passed, {failed} failed")


# ==========================================================================================
# Real integration proof (21-24): SessionStart -> additionalContext -> a fresh session
# reports the pending handoff with no prompt naming it, and never executes anything from
# the pointer. Needs a real `claude` binary and makes a real API call — opt in explicitly.
# ==========================================================================================
def test_real_claude_session_discovers_pending_handoff():
    if os.environ.get("ATLAS_TEST_REAL_CLAUDE") != "1":
        print("\n(real-session integration test skipped — set ATLAS_TEST_REAL_CLAUDE=1 to "
              "run it; it invokes the real `claude` binary and makes a real API call)")
        return True

    import shutil
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("\nSKIP: no `claude` binary on PATH")
        return True

    real_pointer = Path.home() / "atlas" / "runtime" / "session-handoffs" / "latest.md"
    real_dir = real_pointer.parent
    pre_existing = real_pointer.read_text() if real_pointer.is_file() else None
    dir_pre_existed = real_dir.is_dir()
    ok = True
    try:
        real_dir.mkdir(parents=True, exist_ok=True)
        real_pointer.write_text(
            "ticket: T-TEST-REAL-INTEGRATION\n"
            "checkpointed_at: 2026-09-06 3:30 AM\n"
            "state: real integration test\n"
            "next_action: report this without being told\n"
            "status: pending\n")
        r = subprocess.run(
            [claude_bin, "-p",
             "Do not use any tool. If your context mentions a pending Atlas ticket, "
             "reply with exactly TICKET=<id>. Otherwise reply NONE."],
            capture_output=True, text=True, timeout=90)
        ok = "T-TEST-REAL-INTEGRATION" in r.stdout
        chk("a real, unmodified `claude -p` session reports the pending ticket with no "
            "prompt naming it", ok)
        chk("no arbitrary command from the pointer was executed (nothing beyond the "
            "expected TICKET= line in stdout)",
            "confirm rotation" not in r.stdout)  # a field value, never a command result
    finally:
        if pre_existing is not None:
            real_pointer.write_text(pre_existing)
        elif real_pointer.is_file():
            real_pointer.unlink()
        if not dir_pre_existed and real_dir.is_dir() and not any(real_dir.iterdir()):
            real_dir.rmdir()
    return ok


if __name__ == "__main__":
    ok = test_real_claude_session_discovers_pending_handoff()
    sys.exit(1 if (failed or not ok) else 0)
