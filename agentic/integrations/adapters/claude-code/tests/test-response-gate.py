import json, subprocess, sys
from pathlib import Path
G = str(Path(__file__).resolve().parent.parent / "ai-response-gate")
CASES = [
    # (prompt, expect additionalContext present)
    ("جرب هذا الطلب بالعربي", True),
    ("رد بالعربي من فضلك", True),
    ("finish the PR review please", False),
    ("answer this question about the API", False),  # bare English trigger word: not gated
    ("", False),
    ("mixed text with a stray ا letter", True),
]
bad = 0
for prompt, want in CASES:
    out = subprocess.run([G], input=json.dumps({"prompt": prompt}),
                          capture_output=True, text=True)
    got = bool(out.stdout.strip())
    ok = got == want
    bad += not ok
    if got:
        payload = json.loads(out.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
        # Not a literal string from one policy revision — the policy text itself is
        # user-editable content that gets rewritten over time. Check structure instead:
        # non-trivial content that actually names the Arabic-mode behavior it gates.
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert len(ctx) > 40, f"additionalContext suspiciously short: {ctx!r}"
        assert "arabic" in ctx.lower(), f"additionalContext doesn't mention Arabic: {ctx!r}"
    label = prompt[:40] or "(empty)"
    print(f"  {'PASS' if ok else 'FAIL'}  gated={got!s:<5} (want {want!s:<5}) {label}")
    assert out.returncode == 0, f"non-zero exit for {label!r}"

# malformed stdin must never crash or block the prompt
out = subprocess.run([G], input="not json", capture_output=True, text=True)
ok = out.returncode == 0 and out.stdout.strip() == ""
bad += not ok
print(f"  {'PASS' if ok else 'FAIL'}  gated=False (want False) (malformed stdin)")

print(f"\n  {len(CASES) + 1 - bad}/{len(CASES) + 1} passed")
sys.exit(1 if bad else 0)
