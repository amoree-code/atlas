import json, subprocess, sys
from pathlib import Path
G = str(Path(__file__).resolve().parent.parent / "ai-guard-push")
CASES = [
 # (command, expected)
 ("git status", "allow"), ("git commit -m ok", "allow"), ("pnpm run build", "allow"),
 ("git push origin feat/x", "ask"),
 ("cd ~/Documents/x && git push", "ask"),
 ("git fetch && git rebase main && git push", "ask"),
 ("git push --force origin main", "deny"),
 ("git push -f origin main", "deny"),
 ("git push --force-with-lease origin feat/x", "ask"),
 ("git push origin --delete old", "deny"),
 ("gh pr create --fill", "ask"),
 ("gh pr merge 12", "deny"),
 ("gh repo delete foo", "deny"),
 ("git remote set-url origin git@x", "ask"),
 # false-positive guards: text ABOUT commands must not trip it
 ("""python3 - <<'PY'\nopen('d.md','w').write("never run gh pr merge or git push --force")\nPY""", "allow"),
 ("cat > notes.md <<'EOF'\nrule: git push needs approval; gh pr merge is banned\nEOF", "allow"),
 ("echo 'git push --force'", "allow"),
 ("grep -r 'git push' ./docs", "allow"),
 # ...but a real command after a heredoc still trips
 ("cat > a.md <<'EOF'\nhello\nEOF\ngit push origin main", "ask"),
]
bad = 0
for cmd, want in CASES:
    out = subprocess.run([G], input=json.dumps({"tool_name":"Bash","tool_input":{"command":cmd}}),
                         capture_output=True, text=True).stdout
    got = json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out.strip() else "allow"
    ok = got == want
    bad += not ok
    label = cmd.replace("\n", "\\n")[:58]
    print(f"  {'PASS' if ok else 'FAIL'}  {got:<5} (want {want:<5}) {label}")
print(f"\n  {len(CASES)-bad}/{len(CASES)} passed")
sys.exit(1 if bad else 0)
