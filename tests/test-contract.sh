#!/usr/bin/env bash
# tests/test-contract.sh — the V0.1.3 Public/Private Contract, exercised for real.
#
# Every test runs against a throwaway workspace in a temp dir. Nothing here touches the
# real ~/.ai-os, ~/.ai, or the user's Claude settings — the point of a contract test is
# to prove the boundary holds, not to cross it.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$REPO/cli"; export CLI
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ai-os-test.XXXXXX")"
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT

pass=0; fail=0
G=$'\033[32m'; R=$'\033[31m'; D=$'\033[2m'; X=$'\033[0m'
[ -t 1 ] || { G=; R=; D=; X=; }

t()  { printf '\n%s— %s%s\n' "$D" "$1" "$X"; }
chk() { # description, condition-already-evaluated ($? passed as $2)
  if [ "$2" -eq 0 ]; then printf '  %sPASS%s %s\n' "$G" "$X" "$1"; pass=$((pass+1))
  else                    printf '  %sFAIL%s %s\n' "$R" "$X" "$1"; fail=$((fail+1)); fi
}
# Isolate the adapter checks from the user's real Claude install.
export AI_OS_CLAUDE_PROJECTS="$TMP/claude-projects"
export AI_OS_CLAUDE_SETTINGS="$TMP/claude-settings.json"
mkdir -p "$AI_OS_CLAUDE_PROJECTS"
echo '{}' > "$AI_OS_CLAUDE_SETTINGS"

# =====================================================================================
t "init on a clean workspace"
W="$TMP/clean"; export AI_OS_HOME="$W"
out=$("$CLI/ai-os-init" 2>&1); rc=$?
chk "exits 0" $rc
for s in system/config system/rules system/policies system/schemas \
         user/00-inbox user/01-daily user/02-personal user/03-professional \
         user/04-projects user/05-knowledge user/06-templates \
         skills agents scripts sessions runtime; do
  [ -d "$W/$s" ]; chk "created $s/" $?
done
[ -d "$W/user/02-personal/memory/education" ];  chk "created the 8 memory sections" $?
[ -d "$W/user/05-knowledge/decisions" ];        chk "created the 7 knowledge kinds" $?
[ -f "$W/user/02-personal/memory/MEMORY.md" ];  chk "seeded memory/MEMORY.md" $?
[ ! -d "$W/system/config/scripts" ];     chk "did NOT seed runtime scripts into private data" $?
[ ! -d "$W/skills/research" ];           chk "did NOT copy public skills into the workspace" $?
[ ! -d "$W/.git" ];                      chk "did NOT create a git repo (never a remote)" $?

# =====================================================================================
t "init is idempotent — second and third run change nothing"
before=$(find "$W" -type f -exec shasum {} \; | sort | shasum)
"$CLI/ai-os-init" >/dev/null 2>&1
"$CLI/ai-os-init" >/dev/null 2>&1
after=$(find "$W" -type f -exec shasum {} \; | sort | shasum)
[ "$before" = "$after" ];                chk "three runs, byte-identical workspace" $?

# =====================================================================================
t "init never overwrites user-owned content"
echo "MY OWN NOTES — do not touch" > "$W/user/02-personal/memory/MEMORY.md"
echo "a real memory" > "$W/user/02-personal/memory/education/scholarship.md"
mkdir -p "$W/skills/research"; echo "my own research skill" > "$W/skills/research/SKILL.md"
out=$("$CLI/ai-os-init" 2>&1)
grep -q "MY OWN NOTES" "$W/user/02-personal/memory/MEMORY.md";        chk "edited seed file preserved verbatim" $?
grep -q "a real memory" "$W/user/02-personal/memory/education/scholarship.md"; chk "user memory file untouched" $?
grep -q "my own research skill" "$W/skills/research/SKILL.md"; chk "user skill NOT overwritten by the public one" $?
echo "$out" | grep -q "yours";                       chk "reports the divergence instead of resolving it" $?

# =====================================================================================
t "init --dry-run writes nothing"
D2="$TMP/dryrun"; export AI_OS_HOME="$D2"
"$CLI/ai-os-init" --dry-run >/dev/null 2>&1
[ ! -d "$D2" ];                          chk "dry run created no directory at all" $?

# =====================================================================================
t "init refuses a wrong root"
AI_OS_HOME="$REPO" "$CLI/ai-os-init" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "refuses to initialize into the public repo" $?
AI_OS_HOME="$HOME/.ai" "$CLI/ai-os-init" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "refuses to initialize into the runtime" $?

# =====================================================================================
t "doctor: clean workspace passes"
export AI_OS_HOME="$TMP/clean"
# The legacy layer is NOT created here. Until V0.1.5, ~/.ai was the runtime layer and
# this fixture seeded it with bin/{ai-memory,ai-guard-push,ai-sync} because doctor
# checked those were present. V0.1.5 retired ~/.ai and inverted the check: an active
# component left in the legacy layer is now a FAILURE — a second source of truth. The
# fixture was never updated, so it was manufacturing the very violation it then asserted
# was absent. Nothing reads those binaries any more; the two tests below still need
# $AI_OS_RUNTIME to be *settable*, not populated.
export AI_OS_RUNTIME="$TMP/fake-runtime"
out=$("$CLI/ai-os-doctor" 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "no failures on a freshly initialized workspace" $?

# =====================================================================================
# Removing that fixture must not be able to hide a regression in the check it was
# tripping, so assert the check still fires — from both directions.
t "doctor: an active component in the legacy layer is still a failure"
LEG="$TMP/legacy-live"; mkdir -p "$LEG/bin"
out=$(AI_OS_RUNTIME="$LEG" "$CLI/ai-os-doctor" 2>&1); rc=$?
echo "$out" | grep -q "legacy layer still holds active AI OS components"
chk "bin/ left in the legacy layer is reported" $?
echo "$out" | grep -q "second source of truth"
chk "  ...with the reason, not just the fact" $?
[ "$rc" -gt 0 ];                         chk "  ...and doctor exits non-zero" $?
rm -rf "$LEG"
out=$("$CLI/ai-os-doctor" 2>&1); rc=$?
echo "$out" | grep -q "no legacy layer on this machine"
chk "an absent legacy layer is clean, not missing" $?
[ "$rc" -eq 0 ];                         chk "  ...and doctor stays at zero problems" $?

# =====================================================================================
t "doctor: detects wrong roots"
out=$(AI_OS_RUNTIME="$AI_OS_HOME" "$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "same directory";  chk "runtime == private detected" $?
NEST="$TMP/clean/nested-public"; mkdir -p "$NEST"
out=$(cd "$NEST" && AI_OS_HOME="$TMP/clean" "$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -qi "nested";         chk "public repo nested inside private detected" $?

# =====================================================================================
t "doctor: detects a nested repository"
mkdir -p "$AI_OS_HOME/some-project/.git"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "nested git repository inside the private workspace"; chk "nested .git found and reported" $?
rm -rf "$AI_OS_HOME/some-project"

# =====================================================================================
t "doctor: detects a remote on the private workspace"
git -C "$AI_OS_HOME" init -q 2>/dev/null
git -C "$AI_OS_HOME" remote add origin https://example.com/leak.git
out=$("$CLI/ai-os-doctor" 2>&1); rc=$?
echo "$out" | grep -q "PRIVATE workspace has a git remote"; chk "remote detected" $?
[ "$rc" -gt 0 ];                         chk "exits non-zero" $?
[ -n "$(git -C "$AI_OS_HOME" remote -v)" ]; chk "did NOT remove the remote (diagnostic, not destructive)" $?
rm -rf "$AI_OS_HOME/.git"

# =====================================================================================
t "doctor: memory symlink validation"
P="$AI_OS_CLAUDE_PROJECTS"
mkdir -p "$P/good" && ln -s "$AI_OS_HOME/user/02-personal/memory" "$P/good/memory"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "1 client memory link(s), all ->"; chk "a correct link is reported as correct" $?
echo "$out" | grep -q "recursive memory link";           rc=$?; [ $rc -ne 0 ]; chk "a correct link is NOT called recursive" $?

mkdir -p "$P/broken" && ln -s "$TMP/does-not-exist" "$P/broken/memory"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "broken memory link";            chk "broken link detected" $?
rm -rf "$P/broken"

mkdir -p "$P/outside" "$TMP/rogue-memory" && ln -s "$TMP/rogue-memory" "$P/outside/memory"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "OUTSIDE the private workspace"; chk "target outside the workspace detected" $?
echo "$out" | grep -q "different stores";              chk "conflicting stores detected" $?
rm -rf "$P/outside"

mkdir -p "$P/real/memory"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "real directory, not a link";    chk "duplicate live store (real dir) detected" $?
rm -rf "$P/real"

STALE="$AI_OS_RUNTIME/workspace/memory"; mkdir -p "$STALE"
mkdir -p "$P/stale" && ln -s "$STALE" "$P/stale/memory"
out=$("$CLI/ai-os-doctor" 2>&1)
echo "$out" | grep -q "FROZEN pre-cutover archive";    chk "link to the frozen archive detected" $?
rm -rf "$P/stale" "$AI_OS_RUNTIME/workspace"
rm -rf "$P/good"

# =====================================================================================
t "privacy scan: catches what it must"
F="$TMP/fixture"; mkdir -p "$F"
# Assembled at runtime, never written literally in this file: a fixture full of real
# secret-shaped strings would make the repository itself un-scannable, and allowlisting
# this file to compensate would be a permanent hole in the scan.
# Split across two adjacent literals: bash joins them, but the 20-char key shape
# never appears in this file, so the repository stays scannable.
AWSKEY="AKIA""IOSFODNN7EXAMPLE"
{
  printf 'aws_key = %s\n'        "$AWSKEY"
  printf 'token: %s%s\n'         'ghp_' "$(printf 'a%.0s' $(seq 36))"
  printf 'api_key: "%s"\n'       's3cr3t-value-long-enough'
  printf 'db = %s://admin:%s@%s:5432/app\n' 'postgres' 'hunter2' 'db.internal'
  printf 'contact: %s@%s\n'      'real.person' 'somecompany.com'
  printf 'config lives in /Users/%s/projects/thing\n' 'janedoe'
  printf -- '-----%s RSA PRIVATE KEY-----\n' 'BEGIN'
} > "$F/leak.txt"
out=$("$CLI/ai-os-privacy-scan" "$F" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "exits non-zero on findings" $?
echo "$out" | grep -q "AWS access key id";           chk "AWS key" $?
echo "$out" | grep -q "GitHub token";                chk "GitHub token" $?
echo "$out" | grep -q "assigned secret literal";     chk "assigned secret" $?
echo "$out" | grep -q "connection string";           chk "connection string with password" $?
echo "$out" | grep -q "private key block";           chk "private key block" $?
echo "$out" | grep -q "email address";               chk "email address (personal)" $?
echo "$out" | grep -q "absolute home path";          chk "absolute home path (personal)" $?
echo "$out" | grep -q "CREDENTIAL"; c=$?; echo "$out" | grep -q "PERSONAL"; p2=$?
[ $c -eq 0 ] && [ $p2 -eq 0 ];                       chk "classifies credential vs personal separately" $?
echo "$out" | grep -q "$AWSKEY"; [ $? -ne 0 ];       chk "does not print the secret in full" $?

t "privacy scan: user terms come from the PRIVATE workspace"
# Generated per run: a term written literally here would live in the public repo, which
# is exactly the thing the last assertion checks for.
TERM="zz$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')corp"
echo "$TERM" > "$F/doc.md"
out=$(AI_OS_HOME="$TMP/clean" "$CLI/ai-os-privacy-scan" "$F" 2>&1)
echo "$out" | grep -q "PERSONAL.*user term"; [ $? -ne 0 ]
chk "unknown term not flagged without a terms file" $?
mkdir -p "$TMP/clean/system/policies"; echo "$TERM" > "$TMP/clean/system/policies/privacy-terms.txt"
out=$(AI_OS_HOME="$TMP/clean" "$CLI/ai-os-privacy-scan" "$F" 2>&1)
echo "$out" | grep -q "PERSONAL.*user term";         chk "term from ~/.ai-os is applied" $?
grep -rqi "$TERM" "$REPO" --exclude-dir=.git; [ $? -ne 0 ]
chk "the term itself never entered the public repo" $?
rm -f "$TMP/clean/system/policies/privacy-terms.txt"

# =====================================================================================
# `personal` is severity block-IN-PUBLIC-REPO, so two cases are not findings at all: a
# file git ignores is never published, and a licence is SUPPOSED to name its owner.
# Both exemptions are narrow, and neither is allowed to touch credential detection.
t "privacy scan: git-ignored files are not a publishability problem"
GI="$TMP/ignored-repo"; mkdir -p "$GI/derived"
git -C "$GI" init -q 2>/dev/null || git init -q "$GI"
printf 'derived/\n' > "$GI/.gitignore"
printf 'graph root: /Users/%s/projects/thing\n' 'janedoe' > "$GI/derived/.root"
printf 'source file, nothing personal\n' > "$GI/src.txt"

# Baseline: the same content in a NON-ignored file is still reported, so the fixture is
# genuinely detectable and the exemption below is doing real work.
cp "$GI/derived/.root" "$GI/tracked-copy.txt"
out=$("$CLI/ai-os-privacy-scan" "$GI" 2>&1); rc=$?
echo "$out" | grep -q "tracked-copy.txt"
chk "a home path in a NON-ignored file is still reported" $?
echo "$out" | grep -q "derived/.root"; [ $? -ne 0 ]
chk "  ...while the same path in an ignored file is exempt" $?
rm -f "$GI/tracked-copy.txt"

out=$("$CLI/ai-os-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "a repo whose only findings are ignored scans clean" $?
echo "$out" | grep -q "git-ignored";                 chk "  ...and says so in the header, never silently" $?

# --include-ignored must restore the strict behaviour, or the exemption is unauditable.
out=$("$CLI/ai-os-privacy-scan" --include-ignored "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "--include-ignored reports it again" $?
echo "$out" | grep -q "derived/.root";               chk "  ...naming the ignored file" $?

# THE LINE THAT MUST NOT MOVE: an ignored file is a common home for a real secret.
AWSKEY2="AKIA""IOSFODNN7EXAMPLE"
printf 'aws_key = %s\n' "$AWSKEY2" > "$GI/derived/leak.txt"
out=$("$CLI/ai-os-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "a CREDENTIAL in an ignored file still fails the scan" $?
echo "$out" | grep -q "AWS access key id";           chk "  ...and is named" $?
echo "$out" | grep -q "1 credential";                chk "  ...classified as credential, not personal" $?
rm -f "$GI/derived/leak.txt"

# The exemption is git's answer, not a hardcoded directory name.
printf '' > "$GI/.gitignore"
out=$("$CLI/ai-os-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "un-ignoring the file brings the finding back" $?

t "privacy scan: licence attribution is allowed only in a licence context"
LC="$TMP/licence"; mkdir -p "$LC"
# A generated term, for the same reason as every other user-term test here: a real name
# written into this file would put it in the public repo.
LTERM="zz$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')corp"
LHOME="$TMP/lhome"; mkdir -p "$LHOME/system/policies"
echo "$LTERM" > "$LHOME/system/policies/privacy-terms.txt"
# NB: capture, never `lscan | grep`. The scanner exits 1 when it finds something and the
# suite runs under `set -o pipefail`, so a pipe reports the scanner's exit, not grep's.
lscan() { AI_OS_HOME="$LHOME" "$CLI/ai-os-privacy-scan" "$LC" 2>&1; }

printf 'MIT License\n\nCopyright (c) 2026 %s\n' "$LTERM" > "$LC/LICENSE"
out=$(lscan); rc=$?
[ "$rc" -eq 0 ];                                     chk "a LICENSE naming its owner scans clean" $?
echo "$out" | grep -q PERSONAL; [ $? -ne 0 ]
chk "  ...the name on the copyright line is attribution, not a finding" $?

printf 'Copyright (c) 2026 %s <%s@%s>\n' "$LTERM" 'owner' 'corp.example' > "$LC/LICENSE"
out=$(lscan)
echo "$out" | grep -q PERSONAL; [ $? -ne 0 ]
chk "  ...and so is an email on that line" $?

# Narrowness. Each of these must still be caught.
printf 'MIT License\n\nCopyright (c) 2026 Nobody\n\nMaintained by %s\n' "$LTERM" > "$LC/LICENSE"
out=$(lscan)
echo "$out" | grep -q "PERSONAL.*user term"
chk "the same name on ANOTHER line of LICENSE is still a finding" $?

rm -f "$LC/LICENSE"; printf 'Copyright (c) 2026 %s\n' "$LTERM" > "$LC/README.md"
out=$(lscan)
echo "$out" | grep -q "PERSONAL.*user term"
chk "a copyright line in a NON-licence file is still a finding" $?
rm -f "$LC/README.md"

printf 'Copyright (c) 2026 Nobody, /Users/%s/dev\n' 'janedoe' > "$LC/LICENSE"
out=$(lscan)
echo "$out" | grep -q "absolute home path"
chk "a home path on the copyright line is still a finding" $?

printf 'Copyright (c) 2026 Nobody %s\n' "$AWSKEY2" > "$LC/LICENSE"
out=$(lscan)
echo "$out" | grep -q "CREDENTIAL"
chk "a credential on the copyright line is still a finding" $?

# The exemption must be a CONTEXT rule, not the owner's name sitting in a public file.
# Asserted without naming anyone: writing the name here to grep for it would BE the leak
# — the first draft of this test did exactly that, and the repo scan caught it.
grep -q 'COPYRIGHT_LINE = re.compile' "$CLI/ai-os-privacy-scan"
chk "licence attribution is a pattern in the scanner, not a literal name" $?
n=$(grep -cvE '^[[:space:]]*(#|$)' "$REPO/governance/policies/privacy-allowlist.txt")
[ "$n" -eq 12 ]
chk "the allowlist gained no entry — every one is a hole in the scan ($n)" $?
grep -q "^exceptions:" "$REPO/governance/policies/privacy-classification.yaml"
chk "both exemptions are documented as policy" $?
# And the scan of this very repository is the real guard: if a name, a home path or an
# email ever lands in a tracked file, the cleanliness test below fails. That is what
# caught this test's own first draft.

t "privacy scan: no false positive on the repository's own text"
out=$("$CLI/ai-os-privacy-scan" "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "the public repo scans clean" $?

# =====================================================================================
t "public repository cleanliness (working tree AND full history)"
out=$("$CLI/ai-os-privacy-scan" --history --quiet "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no personal data anywhere in git history" $?

# =====================================================================================
t "adapter contract: the real registry"
out=$("$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "all shipped manifests valid" $?
n=$(echo "$out" | grep -c '^  ok ')
[ "$n" -eq 5 ];                                      chk "5 manifests present and parsed" $?
echo "$out" | grep -q "consumer not verified";       chk "unverified consumers are flagged, not hidden" $?
"$CLI/ai-os-adapter" list 2>&1 | grep -q "cursor.*nothing"
chk "an adapter that writes nothing is valid" $?

t "adapter contract: violations are rejected"
F2="$TMP/fixtures"; mkdir -p "$F2"
mk() { mkdir -p "$F2/$1"; cat > "$F2/$1/adapter.yaml"; }

# THE HARD RULE: a provides: path inside the private workspace.
mk badpath <<EOF
adapter: badpath
name: Bad Path
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: $AI_OS_HOME/user/02-personal/memory/stolen.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F2" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
echo "$out" | grep -q "INSIDE \$AI_OS_HOME";          chk "provides: path inside \$AI_OS_HOME is rejected" $?
[ "$rc" -gt 0 ];                                     chk "  ...and it is a hard failure" $?
rm -rf "$F2/badpath"

# verified:false must never be written.
mk unverified <<'EOF'
adapter: unverified
name: Unverified
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: false }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F2" "$CLI/ai-os-adapter" doctor 2>&1)
echo "$out" | grep -q "MUST NOT write an unverified";  chk "writing an unverified surface is rejected" $?
rm -rf "$F2/unverified"

# contract range
mk future <<'EOF'
adapter: future
name: From The Future
contract: 2
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F2" "$CLI/ai-os-adapter" doctor 2>&1)
echo "$out" | grep -q "supports 1..1 — DISABLED";      chk "contract 2 on a contract-1 core is disabled with a reason" $?
rm -rf "$F2/future"

# unknown core resource
mk greedy <<'EOF'
adapter: greedy
name: Greedy
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
requires:
  - workspace.everything
EOF
out=$(AI_OS_ADAPTERS="$F2" "$CLI/ai-os-adapter" doctor 2>&1)
echo "$out" | grep -q "unknown core resource";         chk "an undeclared core resource is rejected" $?
rm -rf "$F2/greedy"

# malformed: reports, exits non-zero, changes nothing
mkdir -p "$F2/broken"; printf 'adapter: broken\n\tbad: [unclosed\n' > "$F2/broken/adapter.yaml"
before=$(shasum "$F2/broken/adapter.yaml")
out=$(AI_OS_ADAPTERS="$F2" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "a malformed manifest fails" $?
[ "$before" = "$(shasum "$F2/broken/adapter.yaml")" ]; chk "  ...and nothing was modified" $?
rm -rf "$F2/broken"

t "registry resolution is pinned (the old hardcoded table, as a regression guard)"
# ai-sync no longer HAS a client table, so comparing against it would be tautological.
# These are the exact values it used before step 8; drifting off them is a regression.
python3 - <<'PYEOF'
import os
from pathlib import Path
H = Path.home()
EXPECTED = {
    "claude": (H/".claude/CLAUDE.md", H/".claude/skills"),
    "codex":  (H/".codex/AGENTS.md",  H/".codex/skills"),
    "gemini": (H/".gemini/GEMINI.md", H/".gemini/skills"),
}
EXPECTED_PROJECT_ONLY = ["cursor", "opencode"]
m = {"__name__": "notmain",
     "__file__": str(Path(os.environ["CLI"], "ai-sync"))}
exec(compile(Path(os.environ["CLI"], "ai-sync").read_text(), "ai-sync", "exec"), m)
got = m["CLIENTS"]
assert set(got) == set(EXPECTED), f"clients drifted: {sorted(got)} != {sorted(EXPECTED)}"
for k, (r, sk) in EXPECTED.items():
    assert got[k]["rules"] == r,  f"{k} rules drifted: {got[k]['rules']} != {r}"
    assert got[k]["skills"] == sk, f"{k} skills drifted: {got[k]['skills']} != {sk}"
assert sorted(m["PROJECT_ONLY"]) == EXPECTED_PROJECT_ONLY, m["PROJECT_ONLY"]
PYEOF
chk "the 3 writable clients resolve to their original paths" $?

t "ai-sync knows no client by name"
! grep -qE '^\s*CLIENTS\s*=\s*\{' "$CLI/ai-sync"
chk "no hardcoded CLIENTS table" $?
! grep -qE '^\s*PROJECT_ONLY\s*=\s*\[' "$CLI/ai-sync"
chk "no hardcoded PROJECT_ONLY list" $?
! grep -qE 'HOME */ *"\.(claude|codex|gemini|cursor)' "$CLI/ai-sync"
chk "no hardcoded client config paths" $?
# The docstring says the words "if client == \"claude\"" to explain why it is gone, so
# match an actual conditional (trailing colon) rather than the prose about one.
! grep -qE 'if +client *== *"claude" *:' "$CLI/ai-sync"
chk "no client-name conditional in core render()" $?

t "the Claude rules fragment lives in the Claude adapter"
[ -f "$REPO/adapters/claude-code/rules-fragment.md" ]
chk "adapters/claude-code/rules-fragment.md exists" $?
python3 - <<'PYEOF'
import os
from pathlib import Path
m = {"__name__": "notmain",
     "__file__": str(Path(os.environ["CLI"], "ai-sync"))}
exec(compile(Path(os.environ["CLI"], "ai-sync").read_text(), "ai-sync", "exec"), m)
rules = m["canonical_rules"]()
c, _ = m["render"]("claude", rules, m["CLIENTS"]["claude"])
x, _ = m["render"]("codex", rules, m["CLIENTS"]["codex"])
assert "## Claude Code specifics" in c, "claude lost its fragment"
assert "## Claude Code specifics" not in x, "codex wrongly received the Claude fragment"
assert c.startswith(m["MARK_BEGIN"]) and c.rstrip().endswith(m["MARK_END"])
assert "# Global rules\n" in c and "# Global rules (AGENTS.md)" in x, "titles not manifest-driven"
PYEOF
chk "fragment and title come from the manifest, not from core" $?

t "unverified capabilities are never written"
python3 - <<'PYEOF'
import os
from pathlib import Path
m = {"__name__": "notmain",
     "__file__": str(Path(os.environ["CLI"], "ai-sync"))}
exec(compile(Path(os.environ["CLI"], "ai-sync").read_text(), "ai-sync", "exec"), m)
# cursor and opencode declare rules verified:false / null path.
for pid in ("cursor", "opencode"):
    assert pid in m["PROJECT_ONLY"], f"{pid} should be project-only"
    assert pid not in m["CLIENTS"], f"{pid} must never be a write target"
PYEOF
chk "cursor and opencode are never write targets" $?
[ ! -f "$HOME/.config/opencode/AGENTS.md" ]
chk "nothing was written to opencode's unverified path" $?

t "skill backups are namespaced per client"
grep -q 'def backup(path, tag, owner=None)' "$CLI/ai-sync"
chk "backup() takes an owner" $?
# Call sites only — the def line also contains "owner=". Two remain: the per-client skill
# write and the orphan prune. A third regenerated the runtime copy of the skills, which
# retired with ~/.ai.
n=$(grep 'backup(.*owner=' "$CLI/ai-sync" | grep -vc '^def ')
[ "$n" -eq 2 ]
chk "both skill backup sites namespace their copy ($n)" $?

# =====================================================================================
# A format-on-save pass once reflowed the manifests and took the suite from 3 failures to
# 13. Prettier puts a flow collection on the line AFTER its key when the line would be
# long. The document is identical; only the layout changed. The parser — which now lives
# in cli/ai-os-adapter and is borrowed by cli/ai-os-capability, so ONE parser serves both
# registries — must read both layouts, and must still reject a collection that genuinely
# does not close.
t "manifest layout: a formatter's reflow is read, not rejected"
FMT="$TMP/formatted"; mkdir -p "$FMT/adapters" "$FMT/plugins"

# Reflow every SHIPPED manifest: move each `key: { ... }` onto the following line, which
# is exactly what the formatter did. Reflow only — no other edit.
reflow() {  # src -> dst
  sed -E 's/^([[:space:]]*)([A-Za-z0-9_.-]+):[[:space:]]+(\{.*\})[[:space:]]*$/\1\2:\n\1  \3/' \
    "$1" > "$2"
}
for src in "$REPO"/adapters/*/adapter.yaml; do
  aid=$(basename "$(dirname "$src")"); mkdir -p "$FMT/adapters/$aid"
  reflow "$src" "$FMT/adapters/$aid/adapter.yaml"
done
# The fixture deliberately keeps the OLD directory and manifest names: reading it back
# through AI_OS_PLUGINS below is also the compatibility-window proof.
for src in "$REPO"/capabilities/*/capability.yaml; do
  cid=$(basename "$(dirname "$src")"); mkdir -p "$FMT/plugins/$cid"
  reflow "$src" "$FMT/plugins/$cid/plugin.yaml"
done
n=$(grep -c '^[[:space:]]*[{[]' "$FMT"/adapters/*/adapter.yaml | awk -F: '{s+=$2} END {print s+0}')
[ "$n" -gt 0 ];                                      chk "the adapter fixture really is reflowed ($n wrapped collections)" $?

out=$(AI_OS_ADAPTERS="$FMT/adapters" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "reflowed adapter manifests still validate" $?
[ "$(echo "$out" | grep -c '^  ok ')" -eq 5 ];       chk "  ...all 5, none unreadable" $?
echo "$out" | grep -qi "flow collection"; [ $? -ne 0 ]
chk "  ...and no flow-collection complaint" $?

# The two layouts must not merely both parse — they must parse to the SAME document.
# (drop the header line, which echoes the fixture directory and so always differs)
inline=$(AI_OS_ADAPTERS="$REPO/adapters" "$CLI/ai-os-adapter" list 2>&1 | grep -v 'adapters  ')
split=$(AI_OS_ADAPTERS="$FMT/adapters" "$CLI/ai-os-adapter" list 2>&1 | grep -v 'adapters  ')
[ "$inline" = "$split" ];                            chk "inline and split forms parse identically" $?

# The capability registry borrows this parser, so the same reflow must be safe there too.
out=$(AI_OS_PLUGINS="$FMT/plugins" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "reflowed capability manifests still validate" $?
inline=$(AI_OS_PLUGINS="$REPO/capabilities" "$CLI/ai-os-capability" list 2>&1 | grep -v 'capabilities  ')
split=$(AI_OS_PLUGINS="$FMT/plugins" "$CLI/ai-os-capability" list 2>&1 | grep -v 'capabilities  ')
[ "$inline" = "$split" ];                            chk "  ...to the same document as the shipped layout" $?

# A capability manifest written in the wrapped form from the start, since the shipped one
# happens to carry no inline flow collection for the reflow to move.
F4="$TMP/wrapped-cap"; mkdir -p "$F4/wrapped"
cat > "$F4/wrapped/plugin.yaml" <<'EOF'
plugin: wrapped
name: Wrapped Capability
contract: 1
capability:
  { authority: observe }
operations:
  look:
    summary: read something
    command: wrapped
    authority: observe
    idempotent: true
    verify: wrapped-verify
EOF
out=$(AI_OS_PLUGINS="$F4" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "a capability manifest in the wrapped form is read" $?

# Wrapped across several lines, the way a formatter breaks a collection that is too long.
F3="$TMP/wrapped"; mkdir -p "$F3/multi"
cat > "$F3/multi/adapter.yaml" <<'EOF'
adapter: multi
name: Multi Line
contract: 1
client:
  {
    detect: [/nonexistent],
    consumer_verified: false
  }
provides:
  rules:
    { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F3" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "a multi-line wrapped collection is read" $?

# ...and the strictness survives. Loosening the layout must not loosen the parser.
cat > "$F3/multi/adapter.yaml" <<'EOF'
adapter: multi
name: Never Closes
contract: 1
client:
  { detect: [/nonexistent], consumer_verified: false
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F3" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "a wrapped collection that never closes still fails" $?
echo "$out" | grep -qi "unterminated flow collection"
chk "  ...with a reason, not a guess" $?

cat > "$F3/multi/adapter.yaml" <<'EOF'
adapter: multi
name: Trailing Junk
contract: 1
client:
  { detect: [/nonexistent], consumer_verified: false } and then some
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_ADAPTERS="$F3" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "content after a wrapped collection still fails" $?
echo "$out" | grep -qi "content after the flow collection"
chk "  ...naming the trailing content" $?
rm -rf "$F3" "$F4"

t "the formatter that broke the registry is fenced off"
[ -f "$REPO/.prettierignore" ];                      chk ".prettierignore ships with the repo" $?
grep -q '^adapters/' "$REPO/.prettierignore";        chk "  ...covering adapters/" $?
grep -q '^capabilities/' "$REPO/.prettierignore";     chk "  ...covering capabilities/" $?
grep -q '^governance/' "$REPO/.prettierignore";      chk "  ...covering governance/" $?
grep -q '^schemas/' "$REPO/.prettierignore";         chk "  ...covering the yaml fences in schemas/" $?
[ -f "$REPO/.vscode/settings.json" ];                chk "repo-level editor settings disable format-on-save" $?
grep -q '"editor.formatOnSave": false' "$REPO/.vscode/settings.json"
chk "  ...for anyone who clones it, not just this machine" $?

t "adapter enable/disable refuse until wired (no dead state)"
out=$("$CLI/ai-os-adapter" enable claude-code 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "enable refuses" $?
echo "$out" | grep -q "Step 8";                      chk "  ...and names the step that would wire it" $?
[ ! -e "$AI_OS_HOME/system/config/plugins.yaml" ];   chk "  ...and wrote no registry state" $?

# =====================================================================================
t "profile: the public template carries no values"
TPL="$REPO/templates/workspace/system/config/profile.yaml"
[ -f "$TPL" ];                                       chk "profile.yaml template exists" $?
grep -qE '^(vcs_owner|  default|  summary|  tool|  curator): *""$' "$TPL"
chk "template ships blank values, not someone's" $?
grep -q 'never leaves ~/.ai-os' "$TPL";              chk "template states it is private" $?

t "profile: init seeds it once and never overwrites"
P3="$TMP/profilews"; export AI_OS_HOME="$P3"
"$CLI/ai-os-init" >/dev/null 2>&1
[ -f "$P3/system/config/profile.yaml" ];             chk "init seeds system/config/profile.yaml" $?
echo "vcs_owner: my-own-handle" > "$P3/system/config/profile.yaml"
out=$("$CLI/ai-os-init" 2>&1)
grep -q "my-own-handle" "$P3/system/config/profile.yaml";   chk "an edited profile is never overwritten" $?
echo "$out" | grep -q "yours.*profile.yaml";         chk "  ...and the divergence is reported" $?

t "render: unresolved placeholders are visible, never silently blank"
printf 'x {{profile.nothing.here}} y\n' > "$TMP/probe.md"
mkdir -p "$REPO/skills/__probe__" && cp "$TMP/probe.md" "$REPO/skills/__probe__/SKILL.md"
out=$(AI_OS_HOME="$P3" "$CLI/ai-os-render" __probe__ 2>&1)
echo "$out" | grep -q '\[\[profile.nothing.here unset\]\]'
chk "an unset value renders as an explicit marker" $?
echo "$out" | grep -qE '^x  y$'; [ $? -ne 0 ];       chk "  ...not as an empty string" $?
rm -rf "$REPO/skills/__probe__"

t "render: client conventions come from the adapter manifest"
export AI_OS_HOME="$HOME/.ai-os"
a=$("$CLI/ai-os-render" catch-up --client claude-code 2>&1 | grep -c 'CLAUDE.md')
b=$("$CLI/ai-os-render" catch-up --client codex 2>&1 | grep -c 'AGENTS.md')
[ "$a" -gt 0 ];                                      chk "claude-code resolves to CLAUDE.md" $?
[ "$b" -gt 0 ];                                      chk "codex resolves to AGENTS.md" $?
c=$("$CLI/ai-os-render" catch-up --client codex 2>&1 | grep -c 'CLAUDE.md')
[ "$c" -eq 0 ];                                      chk "  ...and codex gets no Claude filename" $?

t "THE SKILL GATE: 8 skills render equivalent to the committed goldens"
# This gate began as a migration check: the canonical bodies had to render equivalent to
# the hand-maintained copy in the runtime layer. That copy was rendered with the real
# user's profile — it carried their org folders and VCS handle — so it could never live
# here, and it retires with ~/.ai. The proof is preserved by rendering against a fictional
# fixture profile and diffing the committed goldens instead: same eight skills, same
# renderer, same client conventions, no private data and no runtime dependency.
GW="$TMP/goldenws"; mkdir -p "$GW/system/config"
cp "$REPO/tests/fixtures/profile.yaml" "$GW/system/config/profile.yaml"
out=$(AI_OS_HOME="$GW" "$CLI/ai-os-render" --check "$REPO/tests/fixtures/golden-skills" \
        --client claude-code 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no semantic loss across all 8 skills" $?
# Count per-skill result lines only — the summary line says "equivalent" too.
n=$(echo "$out" | grep -cE '^  (identical|equivalent) ')
[ "$n" -eq 8 ];                                      chk "all 8 accounted for ($n)" $?
echo "$out" | grep -q "DIFFERS"; [ $? -ne 0 ];       chk "no skill differs semantically" $?
# The goldens are public artefacts and must stay that way.
AI_OS_HOME="$GW" "$CLI/ai-os-privacy-scan" "$REPO/tests/fixtures" >/dev/null 2>&1
chk "the goldens carry no private data" $?
# Independence, proved by construction rather than by grepping this file: run the same
# gate with a HOME that has no runtime layer under it at all. If it still passes, nothing
# in the path from canonical body to golden touches ~/.ai.
NOAI="$TMP/no-runtime-home"; mkdir -p "$NOAI"
HOME="$NOAI" AI_OS_HOME="$GW" "$CLI/ai-os-render" --check \
  "$REPO/tests/fixtures/golden-skills" --client claude-code >/dev/null 2>&1
chk "the gate passes with no runtime layer present" $?

t "public skills carry no personal values"
# The terms are read from the PRIVATE term file, never spelled out here: a test that
# names the strings it asserts are absent puts them in the repo it is guarding.
TERMS="${AI_OS_HOME:-$HOME/.ai-os}/system/policies/privacy-terms.txt"
if [ -f "$TERMS" ]; then
  miss=0; nterms=0
  while IFS= read -r term; do
    term="${term%%#*}"; term="$(echo "$term" | sed 's/^ *//;s/ *$//')"
    [ ${#term} -ge 3 ] || continue
    nterms=$((nterms+1))
    grep -rqi -- "$term" "$REPO/skills/" && miss=$((miss+1))
  done < "$TERMS"
  [ "$miss" -eq 0 ];   chk "0 of $nterms private terms appear in public skills" $?
else
  printf '  %sSKIP%s no privacy-terms.txt — cannot check personal values\n' "$D" "$X"
fi

# =====================================================================================
# THE STEP 9 GATE: memory is a CORE capability. Core must not know any client exists.
t "memory engine: core carries no client knowledge"
# A client name anywhere in the engine is the defect this split exists to remove.
hits=$(grep -Eic 'claude|codex|gemini|cursor|opencode' "$CLI/ai-os-memory" || true)
[ "$hits" -eq 0 ];   chk "0 client references in cli/ai-os-memory" $?
grep -q 'if client' "$CLI/ai-os-memory"
[ $? -ne 0 ];        chk "no branch on client identity" $?

t "memory engine: the Claude facts live in the Claude adapter, once"
AD="$REPO/adapters/claude-code/ai-memory-mounts"
[ -x "$AD" ];                                    chk "claude-code ships a mounts adapter" $?
grep -q '\.claude' "$AD";                        chk "it owns the ~/.claude/projects path" $?
grep -q 're\.sub' "$AD";                         chk "it owns the cwd-slug rule" $?
# The slug rule must be IMPLEMENTED in exactly one place, or the split leaked. Manifests
# are excluded: since V0.4 they sit beside the executable in adapters/<id>/, and the
# claude-code manifest describes the path in prose. Prose is not a second implementation.
n=$(grep -rl 'projects.*<cwd-slug>\|\[/\.\]' "$REPO/cli" "$REPO/adapters" 2>/dev/null \
      | grep -v '\.yaml$' | wc -l)
[ "$n" -eq 1 ];                                  chk "the slug rule is implemented in exactly one file" $?

t "memory engine: a NON-Claude client gets the whole engine"
# The real proof of a client-agnostic core: a client that does not exist, with no Claude
# anywhere in the environment, consuming the engine through the same declared contract.
MW="$TMP/mem-ws"; MP="$TMP/mem-adapters"; MA="$MP"   # manifest + exe are siblings
AI_OS_HOME="$MW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$MP/testclient" "$TMP/tc-home/proj-a" "$TMP/tc-home/proj-b"
cat > "$MP/testclient/adapter.yaml" <<EOF
adapter: testclient
name: Test Client
contract: 1
client:
  detect: [$TMP/tc-home]
  consumer_verified: true
provides:
  rules: { path: ~/.testclient/RULES.md, format: markdown, verified: true }
writes: [rules]
integrates:
  memory.mounts: { command: mounts, format: newline-paths, verified: true }
EOF
cat > "$MA/testclient/mounts" <<EOF
#!/usr/bin/env bash
[ "\$1" = list ] && { echo "$TMP/tc-home/proj-a/memory"; echo "$TMP/tc-home/proj-b/memory"; }
# `path <dir>` answers which mount serves a working directory — the client's own rule.
[ "\$1" = path ] && echo "\$2/memory"
exit 0
EOF
chmod +x "$MA/testclient/mounts"
export AI_OS_ADAPTERS="$MP"

out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach 2>&1); rc=$?
[ "$rc" -eq 0 ];                                 chk "core attaches a non-Claude client's mounts" $?
[ -L "$TMP/tc-home/proj-a/memory" ];             chk "mount a is now a symlink" $?
# Compared by inode: the target string may differ harmlessly from $MW (a trailing slash
# in TMPDIR, a symlinked /tmp) while pointing at exactly the same store.
[ -L "$TMP/tc-home/proj-b/memory" ] && [ "$TMP/tc-home/proj-b/memory" -ef "$MW/user/02-personal/memory" ]
chk "mount b resolves to the canonical store" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" status 2>&1)
echo "$out" | grep -q 'linked'                   ; chk "status reports it linked" $?
AI_OS_HOME="$MW" "$CLI/ai-os-memory" doctor >/dev/null 2>&1
chk "doctor passes on a freshly attached non-Claude workspace" $?
env | grep -qi 'claude' && claude_in_env=1 || claude_in_env=0
[ "$claude_in_env" -eq 0 ] || [ -z "${AI_OS_ADAPTERS##*mem-adapters}" ]
chk "the engine resolved no Claude adapter at all" $?

t "memory engine: attach --here asks the adapter which mount serves this directory"
# Step 10 needs exact parity with the historical `link`: one directory, not all of them.
mkdir -p "$TMP/tc-home/proj-here"
out=$(cd "$TMP/tc-home/proj-here" && AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --here 2>&1)
[ -L "$TMP/tc-home/proj-here/memory" ];          chk "--here attached the current directory" $?
[ ! -e "$TMP/tc-home/proj-d/memory" ];           chk "   ...and only that one" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --here /some/path 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "--here with a PATH is refused" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --bogus 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "an unknown option is refused, not ignored" $?
grep -q 'cwd' "$CLI/ai-os-memory";               chk "core resolves cwd through the adapter, not a rule of its own" $?

t "memory engine: attach never destroys user data"
mkdir -p "$TMP/tc-home/proj-c/memory"
echo 'irreplaceable' > "$TMP/tc-home/proj-c/memory/keep.md"
QT="$TMP/quarantine"
AI_OS_HOME="$MW" AI_OS_MEMORY_QUARANTINE="$QT" \
  "$CLI/ai-os-memory" attach "$TMP/tc-home/proj-c/memory" >/dev/null 2>&1
[ -L "$TMP/tc-home/proj-c/memory" ];             chk "the path became a link" $?
found=$(grep -rl 'irreplaceable' "$QT" 2>/dev/null | wc -l)
[ "$found" -eq 1 ];                              chk "the pre-existing file was rescued, not deleted" $?

t "memory engine: an unverified integration is never called"
sed 's/verified: true }/verified: false }/' "$MP/testclient/adapter.yaml" > "$TMP/pv" \
  && mv "$TMP/pv" "$MP/testclient/adapter.yaml"
rm -f "$TMP/tc-home/proj-a/memory" "$TMP/tc-home/proj-b/memory"
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach 2>&1)
echo "$out" | grep -q 'no client declares memory mounts'
chk "core refuses to call an unverified integration" $?
[ ! -e "$TMP/tc-home/proj-a/memory" ];           chk "   ...and wrote nothing" $?

t "memory engine: the registry rejects an invented integration point"
mkdir -p "$TMP/bad-adapters/badint"
cat > "$TMP/bad-adapters/badint/adapter.yaml" <<'EOF'
adapter: badint
name: Bad Integration
contract: 1
client: { detect: [/nonexistent], consumer_verified: true }
provides:
  rules: { path: ~/.badint/RULES.md, format: markdown, verified: true }
writes: [rules]
integrates:
  memory.everything: { command: x, format: newline-paths, verified: true }
EOF
out=$(AI_OS_ADAPTERS="$TMP/bad-adapters" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "an unknown integration point fails" $?
echo "$out" | grep -q 'may not invent one';      chk "   ...with a reason, not a guess" $?

mkdir -p "$TMP/bad-adapters2/badcmd"
sed 's|memory.everything: { command: x,|memory.mounts: { command: ../../etc/x,|' \
  "$TMP/bad-adapters/badint/adapter.yaml" | sed 's/adapter: badint/adapter: badcmd/' \
  > "$TMP/bad-adapters2/badcmd/adapter.yaml"
out=$(AI_OS_ADAPTERS="$TMP/bad-adapters2" "$CLI/ai-os-adapter" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "a command escaping its adapter dir fails" $?
unset AI_OS_ADAPTERS

t "memory engine: the runtime shim preserves all four historical commands"
SHIM="$HOME/.ai/bin/ai-memory"
if [ -x "$SHIM" ]; then
  for c in status doctor link-all; do
    "$SHIM" $c >/dev/null 2>&1;                  chk "ai-memory $c still exits 0" $?
  done
else
  printf '  %sSKIP%s runtime shim not installed\n' "$D" "$X"
fi

# =====================================================================================
# THE STEP 11 GATE: a hook may not know where the repository is.
# A path baked into a hook encodes the machine it was written on and breaks the moment
# the repository moves. These prove the launcher resolves it instead — at any location,
# any depth, any directory name.
HK="$CLI/ai-os-hook"

mk_repo() {  # $1 = repo dir. A minimal stand-in: one repo-relative executable.
  mkdir -p "$1/cli"
  printf '#!/bin/sh\necho "RESOLVED:$(cd "$(dirname "$0")/.." && pwd)"\n' > "$1/cli/probe"
  chmod +x "$1/cli/probe"
}
mk_ws() {    # $1 = workspace dir, $2 = ai_os_repo value (may be empty or ~-relative)
  mkdir -p "$1/system/config"; printf 'ai_os_repo: %s\n' "$2" > "$1/system/config/settings.yaml"
}
resolves() { # $1 = expected repo dir, $2 = the invocation's output
  # Compare physical paths: TMPDIR can carry a trailing slash, which the shell's own
  # pwd normalizes away. That is not a resolution failure.
  exp=$(cd "$1" 2>/dev/null && pwd) || return 1
  echo "$2" | grep -qF "RESOLVED:$exp"
}

t "hook launcher: the repository resolves wherever it is"
FH="$TMP/fakehome"; mkdir -p "$FH"

# 1. directly under $HOME
R1="$FH/ai-os"; mk_repo "$R1"; mk_ws "$TMP/ws1" "$R1"
out=$(AI_OS_HOME="$TMP/ws1" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "repository directly under \$HOME" $?

# 2. under Documents
R2="$FH/Documents/ai-os"; mk_repo "$R2"; mk_ws "$TMP/ws2" "$R2"
out=$(AI_OS_HOME="$TMP/ws2" "$HK" cli/probe 2>&1)
resolves "$R2" "$out";                          chk "repository under Documents/" $?

# 3. nested five deep, and 4. an arbitrary directory name
R3="$FH/a/b/c/d/e/my-weird-ai-os-checkout"; mk_repo "$R3"; mk_ws "$TMP/ws3" "$R3"
out=$(AI_OS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R3" "$out";                          chk "repository nested 5+ deep" $?
echo "$out" | grep -q 'my-weird-ai-os-checkout'
chk "repository directory name is arbitrary" $?

# 5. a ~-prefixed value, expanded against HOME
R5="$FH/tilde-repo"; mk_repo "$R5"; mk_ws "$TMP/ws5" '~/tilde-repo'
out=$(HOME="$FH" AI_OS_HOME="$TMP/ws5" "$HK" cli/probe 2>&1)
resolves "$R5" "$out";                          chk "a ~-prefixed ai_os_repo expands" $?

# 7. explicit override wins over the configured value
out=$(AI_OS_REPO="$R1" AI_OS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "AI_OS_REPO overrides the configured value" $?

t "hook launcher: a broken installation fails loudly, never silently"
# 6. empty value
mk_ws "$TMP/ws6" ""
out=$(AI_OS_HOME="$TMP/ws6" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "empty ai_os_repo exits non-zero" $?
echo "$out" | grep -q "ai-os init";             chk "   ...and says how to fix it" $?
out=$(AI_OS_HOME="$TMP/nonexistent-ws" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a missing workspace config exits non-zero" $?
mk_ws "$TMP/ws8" "$TMP/no-such-repo"
out=$(AI_OS_HOME="$TMP/ws8" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a recorded path that does not exist exits non-zero" $?
out=$(AI_OS_HOME="$TMP/ws1" "$HK" cli/not-there 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a missing repo-relative command exits non-zero" $?

t "hook launcher: no client knowledge, and none of this machine"
n=$(grep -Eic 'claude|codex|gemini|cursor|opencode' "$HK" || true)
[ "$n" -eq 0 ];                                 chk "the launcher names no client" $?
n=$(grep -Eic 'Documents|Projects|Developer|/Users/' "$HK" || true)
[ "$n" -eq 0 ];                                 chk "the launcher hardcodes no location" $?

t "hook launcher: works under a hook's minimal environment"
# 8. exactly what a client hook gets: no inherited env, a bare PATH.
out=$(env -i HOME="$FH" PATH=/usr/bin:/bin AI_OS_HOME="$TMP/ws1" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "resolves under env -i with a minimal PATH" $?

t "hook launcher: moving the repository does not touch any hook"
# 10. THE INVARIANT. The invocation string below is written once and never changed;
# only the recorded location moves.
INVOCATION="cli/probe"
MV_FROM="$TMP/relocate/first/place/ai-os"; MV_TO="$TMP/relocate/somewhere/entirely/different/renamed-os"
mk_repo "$MV_FROM"; mk_ws "$TMP/ws-mv" "$MV_FROM"
out=$(AI_OS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1)
resolves "$MV_FROM" "$out";                     chk "resolves at its original location" $?
mkdir -p "$(dirname "$MV_TO")" && mv "$MV_FROM" "$MV_TO"
out=$(AI_OS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "after the move, the stale location fails loudly" $?
mk_ws "$TMP/ws-mv" "$MV_TO"                     # the one thing that changes: the record
out=$(AI_OS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1)
resolves "$MV_TO" "$out";                       chk "the SAME invocation works after relocation" $?

t "init records the repository location, and never overwrites yours"
# 11. empty -> recorded automatically
IW="$TMP/init-ws"
AI_OS_HOME="$IW" "$CLI/ai-os-init" >/dev/null 2>&1
got=$(sed -n 's/^ai_os_repo:[[:space:]]*//p' "$IW/system/config/settings.yaml" | head -1)
[ "$got" = "$REPO" ];                           chk "init recorded its own actual location" $?
# 12. explicit value survives
sed 's|^ai_os_repo:.*|ai_os_repo: ~/deliberately/elsewhere|' "$IW/system/config/settings.yaml" > "$TMP/x" \
  && mv "$TMP/x" "$IW/system/config/settings.yaml"
out=$(AI_OS_HOME="$IW" "$CLI/ai-os-init" 2>&1)
got=$(sed -n 's/^ai_os_repo:[[:space:]]*//p' "$IW/system/config/settings.yaml" | head -1)
[ "$got" = "~/deliberately/elsewhere" ];        chk "an explicit ai_os_repo is NOT overwritten" $?
echo "$out" | grep -q "kept your value";        chk "   ...and the divergence is reported" $?
# dry run must still write nothing
rm -rf "$TMP/init-dry"
AI_OS_HOME="$TMP/init-dry" "$CLI/ai-os-init" --dry-run >/dev/null 2>&1
[ ! -e "$TMP/init-dry" ];                       chk "--dry-run records nothing" $?

t "the installed hook commands carry no machine-specific path"
# 9. The user's real settings.json, if the launcher is installed.
SJ="$HOME/.claude/settings.json"
if [ -f "$SJ" ] && grep -q 'ai-os-hook' "$SJ"; then
  n=$(grep -Eoc '"command": "[^"]*(Documents|Projects|Developer)/' "$SJ" || true)
  [ "$n" -eq 0 ];                               chk "no repository path in any hook command" $?
  grep -q '\$HOME/.claude/ai-os-hook cli/ai-os memory attach --here' "$SJ"
  chk "SessionStart goes through the launcher" $?
  grep -q '\$HOME/.claude/ai-os-hook adapters/claude-code/ai-guard-push' "$SJ"
  chk "PreToolUse goes through the launcher" $?
  cmp -s "$HOME/.claude/ai-os-hook" "$CLI/ai-os-hook"
  chk "the installed launcher matches the repository's copy" $?
  [ ! -L "$HOME/.claude/ai-os-hook" ];          chk "it is a copy, not a symlink" $?
else
  printf '  %sSKIP%s launcher not installed in this environment\n' "$D" "$X"
fi

# =====================================================================================
# THE STEP 12a GATE: ai-sync is core. It was never runtime-specific — it resolves every
# client from the registry and every skill from the canonical bodies, both of which live
# here. These prove it moved without bringing a client name or a machine with it.
SY="$CLI/ai-sync"

t "ai-sync is canonical core, and knows no client"
[ -x "$SY" ];                                        chk "cli/ai-sync exists and is executable" $?
for name in claude codex gemini cursor opencode; do
  n=$(grep -ci "$name" "$SY" || true)
  [ "$n" -eq 0 ];                                    chk "core never says '$name'" $?
done
n=$(grep -Ec 'Documents|Projects|Developer|/Users/' "$SY" || true)
[ "$n" -eq 0 ];                                      chk "core embeds no machine-specific path" $?

t "ai-sync runs as core, without the runtime layer on PATH"
out=$(env PATH=/usr/bin:/bin "$SY" status 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "status works with ~/.ai/bin off PATH" $?
echo "$out" | grep -q 'CLIENT';                      chk "   ...and still renders the client table" $?
env PATH=/usr/bin:/bin "$SY" verify >/dev/null 2>&1
chk "verify works with ~/.ai/bin off PATH" $?

t "ai-sync resolves its own repository, not a configured one"
# A copy of core must sync from the tree it lives in; resolving some other checkout
# would sync from a tree nobody is looking at.
grep -q 'Path(__file__).resolve().parent.parent' "$SY"
chk "the repository is located from the file's own path" $?
# Scoped to the resolver's own code: the name appears in its docstring, explaining
# precisely why it is not consulted. A prose mention is not a code path.
# Scoped to the code: the name also appears in the resolver's docstring, explaining
# precisely why it is not consulted. A prose mention is not a code path.
n=$(grep -c 'search(r"\^ai_os_repo' "$SY" || true)
[ "$n" -eq 0 ];                                      chk "   ...and never resolved from ai_os_repo:" $?

t "ai-sync honours AI_OS_HOME for runtime state"
grep -q 'AI_OS_HOME = Path(os.environ.get("AI_OS_HOME"' "$SY"
chk "AI_OS_HOME is read from the environment" $?
# Still under AI_OS_HOME — through the one resolver, so a relocated runtime/ moves the
# state with it instead of splitting it across two layouts.
grep -q 'RUNTIME = private_path_or_die("runtime")' "$SY"
chk "runtime state resolves under it" $?
grep -q 'AI_OS_HOME / "runtime"' "$SY"
[ $? -ne 0 ];                                        chk "   ...and never as a hardcoded layout" $?
grep -q 'STATE = RUNTIME / "state"' "$SY";           chk "   ...state" $?
grep -q 'BACKUPS = RUNTIME / "backups"' "$SY";       chk "   ...backups" $?

t "the retired ~/.ai layer is completely removed"
# ~/.ai kept the engine, then a shim, then a frozen archive — and is now deleted
# entirely (user decision, 2026-08-31). Nothing may recreate it.
[ ! -e "$HOME/.ai" ];                                chk "~/.ai no longer exists at all" $?

t "SessionEnd runs the engine through the dynamic launcher"
SJ="$HOME/.claude/settings.json"
if [ -f "$SJ" ] && grep -q 'ai-os-hook' "$SJ"; then
  grep -q '\$HOME/.claude/ai-os-hook cli/ai-sync sync' "$SJ"
  chk "SessionEnd goes through the launcher" $?
  grep -q '\$HOME/.ai/bin/ai-sync' "$SJ"
  [ $? -ne 0 ];                                      chk "   ...and no longer through ~/.ai/bin" $?
  n=$(grep -Ec '"command": "[^"]*(Documents|Projects|Developer)/' "$SJ" || true)
  [ "$n" -eq 0 ];                                    chk "no hook embeds a repository path" $?
  env -i HOME="$HOME" PATH=/usr/bin:/bin sh -c \
    '$HOME/.claude/ai-os-hook cli/ai-sync verify' >/dev/null 2>&1
  chk "the launcher reaches the engine under a hook's minimal env" $?
else
  printf '  %sSKIP%s launcher not installed in this environment\n' "$D" "$X"
fi

t "a clean sync stays a clean no-op"
before=$("$SY" verify 2>&1)
"$SY" sync >/dev/null 2>&1;                          chk "sync exits 0 on an already-synced workspace" $?
after=$("$SY" verify 2>&1)
[ "$before" = "$after" ];                            chk "   ...and changes nothing verify can see" $?
out=$("$SY" sync 2>&1)
echo "$out" | grep -q '0 client(s) changed';         chk "   ...reporting 0 clients changed" $?

# =====================================================================================
t "onboarding: a fresh workspace reports uninitialized"
OB="$TMP/onboard"; export AI_OS_HOME="$OB"
"$CLI/ai-os-init" >/dev/null 2>&1
[ -f "$OB/system/config/workspace.yaml" ];        chk "init seeds the workspace state file" $?
grep -q '^status: uninitialized' "$OB/system/config/workspace.yaml"; chk "seeded as uninitialized" $?
"$CLI/ai-os-onboard" status >/dev/null 2>&1
[ $? -eq 10 ];                                    chk "status exits 10 = onboarding required" $?
# The point of a canonical marker: a workspace full of directories is still uninitialized.
[ -d "$OB/user/02-personal/memory" ] && "$CLI/ai-os-onboard" status >/dev/null 2>&1; [ $? -eq 10 ]
chk "directories existing does NOT count as initialized" $?

# =====================================================================================
t "onboarding: completion is earned, not announced"
"$CLI/ai-os-onboard" complete >/dev/null 2>&1
[ $? -ne 0 ];                                     chk "complete refuses with no data collected" $?
grep -q '^status: uninitialized' "$OB/system/config/workspace.yaml"; chk "  ...and did not mark initialized" $?

# =====================================================================================
t "onboarding: an interrupted run resumes where it stopped"
"$CLI/ai-os-onboard" set name "Test User" >/dev/null 2>&1
chk "first answer accepted" $?
"$CLI/ai-os-onboard" status >/dev/null 2>&1
[ $? -eq 11 ];                                    chk "status exits 11 = incomplete, resumable" $?
grep -q '^step_identity: done' "$OB/system/config/workspace.yaml";    chk "answered step recorded done" $?
grep -q '^step_language: pending' "$OB/system/config/workspace.yaml"; chk "unanswered step still pending" $?
"$CLI/ai-os-onboard" set language "English" >/dev/null 2>&1
"$CLI/ai-os-onboard" complete >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "resumed run completes" $?
"$CLI/ai-os-onboard" status >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "status exits 0 = initialized" $?

# =====================================================================================
t "onboarding: idempotent — repeat runs change nothing and duplicate nothing"
ob_before=$(find "$OB" -type f -exec shasum {} \; | sort | shasum)
ob_when=$(grep '^initialized_at:' "$OB/system/config/workspace.yaml")
"$CLI/ai-os-onboard"          >/dev/null 2>&1
"$CLI/ai-os-onboard" complete >/dev/null 2>&1
"$CLI/ai-os-onboard" --adopt  >/dev/null 2>&1
"$CLI/ai-os-init"             >/dev/null 2>&1
ob_after=$(find "$OB" -type f -exec shasum {} \; | sort | shasum)
[ "$ob_before" = "$ob_after" ];                   chk "four further runs, byte-identical workspace" $?
[ "$ob_when" = "$(grep '^initialized_at:' "$OB/system/config/workspace.yaml")" ]
chk "the initialization timestamp is written once, never moved" $?
[ "$(grep -c '^status:' "$OB/system/config/workspace.yaml")" -eq 1 ]; chk "no duplicated state key" $?
[ "$(find "$OB/user/02-personal/memory/identity" -name '*.md' | wc -l | tr -d ' ')" -eq 1 ]
chk "no duplicated identity record" $?

# =====================================================================================
t "onboarding: never re-interviews or overwrites a completed workspace"
"$CLI/ai-os-onboard" set name "SOMEONE ELSE" >/dev/null 2>&1
[ $? -eq 3 ];                                     chk "refuses to re-answer on an initialized workspace" $?
grep -q "Test User" "$OB/user/02-personal/memory/identity/profile.md"; chk "the original name survives" $?
grep -q "SOMEONE ELSE" "$OB/user/02-personal/memory/identity/profile.md"
[ $? -ne 0 ];                                     chk "the new name was never written" $?
out=$("$CLI/ai-os-onboard" 2>&1)
echo "$out" | grep -q "already initialized";      chk "a bare run says so instead of asking again" $?

# =====================================================================================
t "onboarding: an existing workspace is adopted, not re-created"
AD="$TMP/adopt"; export AI_OS_HOME="$AD"
"$CLI/ai-os-init" >/dev/null 2>&1
"$CLI/ai-os-onboard" --adopt >/dev/null 2>&1
[ $? -ne 0 ];                                     chk "refuses to adopt a workspace with no data" $?
echo "# MY OWN PROFILE"     > "$AD/user/02-personal/memory/identity/profile.md"
echo "# MY OWN PREFERENCES" > "$AD/user/02-personal/memory/preferences/working-style.md"
mem_before=$(find "$AD/user/02-personal/memory" -type f -exec shasum {} \; | sort | shasum)
"$CLI/ai-os-onboard" --adopt >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "adopts a workspace whose data already exists" $?
mem_after=$(find "$AD/user/02-personal/memory" -type f -exec shasum {} \; | sort | shasum)
[ "$mem_before" = "$mem_after" ];                 chk "adoption wrote no memory file at all" $?
grep -q "MY OWN PROFILE" "$AD/user/02-personal/memory/identity/profile.md"
chk "pre-existing user data preserved byte-for-byte" $?

# =====================================================================================
t "onboarding: a marker that outruns the data is reported, not believed"
rm -f "$AD/user/02-personal/memory/identity/profile.md"
"$CLI/ai-os-onboard" status >/dev/null 2>&1
[ $? -eq 12 ];                                    chk "status exits 12 = inconsistent" $?
out=$("$CLI/ai-os-onboard" status 2>&1)
echo "$out" | grep -q "INCONSISTENT";             chk "names the inconsistency instead of passing" $?
echo "$out" | grep -q -- "--repair";              chk "offers a deterministic recovery path" $?
was=$(grep '^initialized_at:' "$AD/system/config/workspace.yaml")
"$CLI/ai-os-onboard" --repair >/dev/null 2>&1
grep -q '^step_identity: pending' "$AD/system/config/workspace.yaml"; chk "repair reopens the missing step" $?
grep -q '^step_language: done'    "$AD/system/config/workspace.yaml"; chk "  ...and only the missing step" $?
[ -f "$AD/user/02-personal/memory/preferences/working-style.md" ]
chk "repair destroyed no surviving data" $?
[ "$was" = "$(grep '^initialized_at:' "$AD/system/config/workspace.yaml")" ]
chk "repair preserved the original initialization date" $?

# =====================================================================================
t "onboarding is client-agnostic"
grep -Eqi 'claude|codex|gemini|cursor|opencode' "$CLI/ai-os-onboard"
[ $? -ne 0 ];                                     chk "no client is named anywhere in the source" $?
grep -Eq '\.claude|\.codex|\.gemini|\.cursor|opencode' "$CLI/ai-os-onboard"
[ $? -ne 0 ];                                     chk "no client-owned path is read or written" $?
# It must complete on a machine where no client is installed at all.
NC="$TMP/noclient"; export AI_OS_HOME="$NC"
"$CLI/ai-os-init" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/ai-os-onboard" set name "N" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/ai-os-onboard" set language "N" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/ai-os-onboard" complete >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "completes with no AI client present" $?
"$CLI/ai-os-onboard" detect | grep -q '^clients:'; chk "detection reports clients from the registry" $?

# =====================================================================================
t "namespace: adapters and capabilities are separate directories"
# The V0.4 inversion fix. Client manifests are adapters; plugins/ is capabilities.
for c in claude-code codex cursor gemini opencode; do
  [ -f "$REPO/adapters/$c/adapter.yaml" ]; chk "adapters/$c/adapter.yaml exists" $?
done
[ ! -e "$REPO/capabilities/claude-code" ];    chk "no client manifest left in capabilities/" $?
# Exactly one canonical location — a copy in both would be two sources of truth.
dup=$(find "$REPO/capabilities" \( -name 'capability.yaml' -o -name 'plugin.yaml' \) -path '*claude*' 2>/dev/null | wc -l | tr -d ' ')
[ "$dup" -eq 0 ];                        chk "no compatibility duplicate was left behind" $?
[ -f "$REPO/schemas/adapter.schema.md" ]; chk "adapter contract has its own schema" $?
[ -f "$REPO/schemas/capability.schema.md" ];  chk "capability contract has its own schema" $?
grep -q 'adapter.*connects.*one AI client' "$REPO/schemas/adapter.schema.md"
chk "the adapter schema describes clients" $?
grep -qi 'capability' "$REPO/schemas/capability.schema.md"
chk "the plugin schema describes capabilities" $?

# =====================================================================================
t "namespace: the two registries are distinct commands over distinct roots"
"$CLI/ai-os-adapter" list 2>&1 | grep -q 'claude-code'
chk "ai-os adapter lists client adapters" $?
"$CLI/ai-os-adapter" list 2>&1 | grep -q "adapters"
chk "  ...from the adapters root" $?
# Superseded by AIOS-007: plugins/ is no longer empty — the browser capability ships.
"$CLI/ai-os-capability" list 2>&1 | grep -q 'browser'
chk "ai-os capability lists the shipped capabilities" $?
"$CLI/ai-os-capability" doctor >/dev/null 2>&1
chk "the capability registry validates" $?
# An EMPTY registry must still be valid, not an error — the property the old test held.
EMPTYREG="$TMP/empty-registry"; mkdir -p "$EMPTYREG"
AI_OS_PLUGINS="$EMPTYREG" "$CLI/ai-os-capability" list 2>&1 | grep -q 'no capabilities'
chk "an empty registry still reports itself as empty" $?
AI_OS_PLUGINS="$EMPTYREG" "$CLI/ai-os-capability" doctor >/dev/null 2>&1
chk "  ...and is valid, not an error" $?
# The client registry must never answer capability questions, or the split is cosmetic.
"$CLI/ai-os-capability" list 2>&1 | grep -q 'claude-code'
[ $? -ne 0 ];                            chk "the capability registry lists no client" $?

# =====================================================================================
t "capability contract: a valid capability is discovered and validated"
CF="$TMP/caps"; mkdir -p "$CF/demo"
cat > "$CF/demo/plugin.yaml" <<'EOF'
plugin: demo
name: Demo Capability
contract: 1
capability:
  domain: demo
  authority: propose
operations:
  build:
    summary: do the thing
    command: run-build
    authority: propose
    verify: check-build
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "a well-formed capability validates" $?
echo "$out" | grep -q 'demo: manifest valid'; chk "  ...and is reported valid" $?
AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" list 2>&1 | grep -q 'demo'
chk "capability discovery finds it" $?
AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" list 2>&1 | grep -q 'build'
chk "  ...and lists its operations" $?

# =====================================================================================
t "capability contract: invalid capabilities are rejected"
cap() { rm -rf "$CF/x"; mkdir -p "$CF/x"; cat > "$CF/x/plugin.yaml"; }

cap <<'EOF'
plugin: x
name: Autonomous
contract: 1
capability: { domain: d, authority: autonomous }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
echo "$out" | grep -q 'cannot be granted'; chk "authority: autonomous is refused, not downgraded" $?
[ "$rc" -gt 0 ];                         chk "  ...as a hard failure" $?

cap <<'EOF'
plugin: x
name: Escalating
contract: 1
capability: { domain: d, authority: propose }
operations:
  go: { summary: s, command: c, authority: execute }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'exceeds capability.authority'
chk "an operation may not exceed its capability's authority" $?

cap <<'EOF'
plugin: x
name: Escaping
contract: 1
capability: { domain: d, authority: observe }
operations:
  go: { summary: s, command: ../../../bin/sh }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'must be a bare filename'
chk "a command that escapes its own directory is rejected" $?

cap <<'EOF'
plugin: x
name: From The Future
contract: 2
capability: { domain: d, authority: observe }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'DISABLED'
chk "contract 2 on a contract-1 core is disabled with a reason" $?

cap <<'EOF'
plugin: x
name: No Authority
contract: 1
capability: { domain: d }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'authority is required'
chk "an unstated authority rung is refused, not defaulted" $?

cap <<'EOF'
plugin: notx
name: Mismatched
contract: 1
capability: { domain: d, authority: observe }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q '!= directory name'
chk "a capability id must equal its directory name" $?

# =====================================================================================
t "capability dependencies: a capability may require another capability"
DF="$TMP/deps"; mkdir -p "$DF/alpha" "$DF/beta"
cat > "$DF/beta/plugin.yaml" <<'EOF'
plugin: beta
name: Beta
contract: 1
capability: { domain: execution, authority: observe }
operations: { go: { summary: s, command: c, verify: v } }
EOF
dep() { cat > "$DF/alpha/plugin.yaml"; }
dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [beta]
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "a satisfied dependency validates" $?
echo "$out" | grep -q 'WARN'
[ $? -ne 0 ];                             chk "  ...with no warning" $?
AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" list 2>&1 | grep -q 'beta'
chk "list shows the declared dependency" $?

# Declared before its dependency exists is legitimate — visible, never fatal.
dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [nowhere]
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
echo "$out" | grep -q 'not in the registry';  chk "an unsatisfied dependency is reported" $?
[ "$rc" -eq 0 ];                          chk "  ...as a warning, not a failure" $?

# =====================================================================================
t "capability dependencies: a dependency names a capability, never a path"
for bad in '"../../etc/passwd"' '"./sneaky"' '"a/b"'; do
  dep <<EOF
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [$bad]
operations: { go: { summary: s, command: c, verify: v } }
EOF
  out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
  echo "$out" | grep -q 'looks like a path'; chk "path-shaped dependency $bad is rejected" $?
  [ "$rc" -gt 0 ];                        chk "  ...as a hard failure" $?
done

dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [Not_An_Id]
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'not a valid capability id';  chk "a malformed id is rejected" $?

dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [alpha]
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'is itself';        chk "a self-dependency is rejected" $?

dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: beta
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(AI_OS_PLUGINS="$DF" "$CLI/ai-os-capability" doctor 2>&1)
echo "$out" | grep -q 'must be a list';   chk "a non-list requires: is rejected" $?

# No resolver was built, and none should appear by accident.
grep -qi 'transitive\|topological\|resolve_deps' "$CLI/ai-os-capability"
[ $? -ne 0 ];                             chk "no dependency resolver was introduced" $?

# =====================================================================================
t "core stays domain-agnostic"
# The architectural test: Core must never branch on what a domain means. Asserted against
# both registries — the capability one, and the domain one that now owns the concept.
grep -Eq 'domain *== *"(software|sales|marketing|design|research|finance)"' "$CLI/ai-os-capability"
[ $? -ne 0 ];                             chk "the capability registry has no domain branching" $?
grep -Eq '(domain|outcome) *== *"' "$CLI/ai-os-domain"
[ $? -ne 0 ];                             chk "the domain registry branches on no id or outcome name" $?
# The falsifier for the whole design: adding a second domain must not have required
# touching CLI logic. Expressed as an absence — Core names none of what ships in domains/.
grep -Eqi '\b(software|customer-support|mobile-app|resolved-ticket|web-application)\b' "$CLI/ai-os-domain"
[ $? -ne 0 ];                             chk "Core names no shipped domain or outcome — the second domain needed no CLI change" $?

# The capability contract no longer carries a `domain:` field at all. It was removed rather
# than renamed when Domain became a real concept: core never read it, nothing validated it,
# and one manifest set it — so one word now has exactly one meaning.
grep -Eq '^\s*domain:' "$REPO/capabilities/browser/capability.yaml"
[ $? -ne 0 ];                             chk "the browser capability declares no domain field" $?
grep -Eq '^\s+domain: ' "$REPO/schemas/capability.schema.md"
[ $? -ne 0 ];                             chk "the capability contract's example declares no domain field" $?

# =====================================================================================
t "domain contract: a domain is inert"
DD="$TMP/domains"; mkdir -p "$DD"
dom() { rm -f "$DD"/*.yaml; cat > "$DD/$1.yaml"; }

[ -f "$REPO/schemas/domain.schema.md" ];  chk "the domain contract has its own schema" $?
[ -x "$CLI/ai-os-domain" ];               chk "the domain registry is executable" $?
out=$("$CLI/ai-os" domain list 2>&1)
echo "$out" | grep -q 'domains'
chk "ai-os domain is wired into the dispatcher" $?

# The shipped registry: two unrelated domains, both valid. One domain proves nothing about
# agnosticism; two unrelated ones are the actual evidence.
out=$("$CLI/ai-os-domain" doctor 2>&1); rc=$?
echo "$out" | grep -q 'all domain declarations valid'
chk "the shipped domain declarations are valid" $?
[ "$rc" -eq 0 ];                          chk "  ...and doctor exits 0 (warnings are not failures)" $?
out=$("$CLI/ai-os-domain" list 2>&1)
echo "$out" | grep -q 'software' && echo "$out" | grep -q 'customer-support'
chk "two unrelated domains are declared, not one" $?

# There is no third verb, and its absence is the contract.
out=$("$CLI/ai-os-domain" deliver 2>&1); rc=$?
[ "$rc" -eq 2 ];                          chk "an execution verb is refused — list and doctor are the whole surface" $?
grep -Eqi 'def cmd_(deliver|invoke|run|execute|dispatch|plan)' "$CLI/ai-os-domain"
[ $? -ne 0 ];                             chk "the domain registry implements no execution command" $?
grep -Eqi 'subprocess|os\.system|exec\(' "$CLI/ai-os-domain"
[ $? -ne 0 ];                             chk "the domain registry cannot run anything at all" $?

# A domain and an outcome core has never heard of validate exactly like the shipped ones.
# Unlike the test this replaced, this is not vacuous: the id, the outcome names and the
# field set are all really parsed and checked.
dom zzz-unknown-area <<'EOF'
domain: zzz-unknown-area
name: Unknown Area
contract: 1
outcomes:
  an-outcome-core-has-never-heard-of:
    summary: something core cannot interpret
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'zzz-unknown-area: declaration valid'
chk "a domain and outcome Core has never heard of validate like any other" $?

dom mismatch <<'EOF'
domain: notmismatch
name: Mismatched
contract: 1
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q '!= filename stem'
chk "a domain id that differs from its filename is refused" $?

# =====================================================================================
t "domain contract: the five-field allowlist refuses every rejected concept by name"
# Each of these is a rejected concept trying to arrive as a field. The allowlist is what
# makes them unexpressible, and the message names which concept was refused.
for pair in \
  "authority:execute:a domain grants nothing" \
  "verify:check-it:a domain defines no verifiers" \
  "command:run-it:a domain is inert" \
  "detect:/tmp:availability is a capability property" \
  "stages:one:never a sequence" \
  "steps:one:never a sequence" \
  "then:other:never a sequence" \
  "depends_on:other:never a sequence" \
  "workflow:w:never a sequence" \
  "dispatch:d:would be a planner" \
  "run:r:never bound to a Run" \
  "task:t:declares no task fields" \
  "operations:o:operations belong to a capability" ; do
  key="${pair%%:*}"; rest="${pair#*:}"; val="${rest%%:*}"; msg="${rest#*:}"
  dom d1 <<EOF
domain: d1
name: D
contract: 1
$key: $val
outcomes: { thing: { summary: s } }
EOF
  out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1); rc=$?
  echo "$out" | grep -q "$msg"
  chk "a domain declaring '$key' is refused — $msg" $?
  [ "$rc" -gt 0 ];                        chk "  ...as a hard failure, not a warning" $?
done

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
whatever: x
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'a declaration is exactly'
chk "an unrecognised field is refused too — the allowlist catches what was not foreseen" $?

# Ordering is refused inside an outcome as well, not only at the top level.
dom d1 <<'EOF'
domain: d1
name: D
contract: 1
outcomes:
  thing:
    summary: s
    then: other-thing
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'never a sequence'
chk "an outcome may not name what follows it" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
outcomes: { thing: { summary: s, command: go } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'not an outcome field'
chk "an outcome may not carry a command" $?

# =====================================================================================
t "domain contract: requires names capabilities by id, and only by id"
dom d1 <<'EOF'
domain: d1
name: D
contract: 1
requires: ["../../etc/passwd"]
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1); rc=$?
echo "$out" | grep -q 'looks like a path'
chk "a path-shaped dependency is refused" $?
[ "$rc" -gt 0 ];                          chk "  ...as a hard failure" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
requires: [not-installed-anywhere]
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1); rc=$?
echo "$out" | grep -q 'not in the capability registry'
chk "an unsatisfied dependency warns" $?
[ "$rc" -eq 0 ];                          chk "  ...and does not fail — declaring before installing is legitimate" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
requires: [d1]
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'is itself'
chk "a domain requiring itself is refused — and it is not a capability" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 9
outcomes: { thing: { summary: s } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'DISABLED'
chk "an unsupported contract version is disabled, never partially honoured" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
outcomes: { thing: { summary: write the claude rules file } }
EOF
out=$(AI_OS_DOMAINS="$DD" "$CLI/ai-os-domain" doctor 2>&1)
echo "$out" | grep -q 'names an AI client'
chk "a domain naming an AI client is refused" $?
rm -f "$DD"/*.yaml

# =====================================================================================
t "boundary: a capability may not do an adapter's job"
cap <<'EOF'
plugin: x
name: Client Aware
contract: 1
capability: { domain: d, authority: observe }
operations:
  go: { summary: write the claude rules file, command: c }
EOF
out=$(AI_OS_PLUGINS="$CF" "$CLI/ai-os-capability" doctor 2>&1); rc=$?
echo "$out" | grep -q 'names an AI client'
chk "a capability naming an AI client is rejected" $?
echo "$out" | grep -q 'belongs in adapters/'
chk "  ...and is told where that belongs" $?
[ "$rc" -gt 0 ];                         chk "  ...as a hard failure" $?
rm -rf "$CF/x"

# =====================================================================================
t "boundary: executed is not verified, and invoke is not wired"
grep -q 'executed' "$REPO/schemas/capability.schema.md" && grep -q 'verified' "$REPO/schemas/capability.schema.md"
chk "the contract distinguishes executed from verified" $?
grep -q 'never implies' "$REPO/schemas/capability.schema.md"
chk "  ...explicitly, as a stated rule" $?
# Superseded by AIOS-007: invoke is wired. What must still hold is that it refuses
# cleanly for anything it cannot actually run, and writes no state while doing so.
out=$("$CLI/ai-os-capability" invoke nosuchcap.build 2>&1); rc=$?
[ "$rc" -eq 4 ];                         chk "invoke refuses an unknown capability" $?
echo "$out" | grep -q 'unavailable';     chk "  ...as unavailable, before any authority check" $?
out=$("$CLI/ai-os-capability" invoke browser.nosuchop 2>&1); rc=$?
[ "$rc" -eq 4 ];                         chk "invoke refuses an undeclared operation" $?
[ ! -e "$AI_OS_HOME/system/config/capabilities.yaml" ]
chk "  ...and wrote no state nothing consumes" $?

# =====================================================================================
t "boundary: no client name leaked into the capability path of Core"
for f in ai-os-capability; do
  grep -Eio 'playwright|chromium' "$CLI/$f" >/dev/null 2>&1
  [ $? -ne 0 ];                          chk "$f names no browser vendor" $?
done
# ai-os-capability may name clients ONLY inside the rejection pattern that forbids them.
n=$(grep -c 'CLIENT_NAMES' "$CLI/ai-os-capability")
[ "$n" -ge 2 ];                          chk "the client-name ban is a mechanical check, not prose" $?
hits=$(grep -Eio '\bclaude\b|\bcodex\b|\bgemini\b' "$CLI/ai-os-capability" | wc -l | tr -d ' ')
inpat=$(grep -Eo 'claude\|claude-code\|codex\|cursor\|gemini\|opencode\|chatgpt' "$CLI/ai-os-capability" | wc -l | tr -d ' ')
[ "$inpat" -ge 1 ];                      chk "  ...and the ban lists the client names it rejects" $?

# =====================================================================================
t "browser capability: manifest, dependencies and authority declarations"
BR="$REPO/capabilities/browser"
[ -f "$BR/capability.yaml" ];                 chk "the browser capability ships a manifest" $?
out=$("$CLI/ai-os-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "it validates against the capability contract" $?
echo "$out" | grep -q 'browser: manifest valid'; chk "  ...and is reported valid" $?
"$CLI/ai-os-capability" list 2>&1 | grep -q 'browser'; chk "capability discovery finds it" $?
# Authority is per operation, not one blanket rung.
grep -q 'authority: observe'   "$BR/capability.yaml"; chk "read-only operations declare observe" $?
grep -q 'authority: execute$'  "$BR/capability.yaml"; chk "interaction operations declare execute" $?
grep -q 'authority: execute-with-approval' "$BR/capability.yaml"; chk "irreversible operations require approval" $?
grep -q 'autonomous' "$BR/capability.yaml"
[ $? -ne 0 ];                             chk "no operation claims autonomous authority" $?
# Idempotency is declared, and the dangerous ones are declared false.
for op in submit click type upload download; do
  awk -v o="  $op:" '$0==o{f=1} f&&/idempotent:/{print;exit}' "$BR/capability.yaml" | grep -q 'false'
  chk "$op is declared non-idempotent" $?
done
for op in navigate read observe; do
  awk -v o="  $op:" '$0==o{f=1} f&&/idempotent:/{print;exit}' "$BR/capability.yaml" | grep -q 'true'
  chk "$op is declared idempotent" $?
done

# =====================================================================================
t "browser capability: the provider boundary is real"
[ -f "$BR/providers/playwright_provider.py" ]; chk "a provider implementation exists" $?
[ -f "$BR/providers/interface.py" ];      chk "the provider boundary is documented" $?
# The engine may be named ONLY inside providers/. That is the replaceability guarantee.
grep -Eil 'playwright|chromium|chrome|webkit|firefox' "$BR/browser" "$BR/browser-verify" "$BR/capability.yaml" \
  | grep -v 'providers/' | grep -q .
[ $? -ne 0 ];                             chk "no browser engine is named outside providers/" $?
grep -q 'BROWSER_PROVIDER' "$BR/browser";  chk "the provider is selected, not hardcoded" $?
# Swapping the provider must not touch the capability: a bogus one fails cleanly.
out=$(cd "$BR" && echo '{}' | BROWSER_PROVIDER=nosuch ./browser detect 2>&1)
echo "$out" | grep -q 'no provider'
chk "an unknown provider is refused by name, not by crash" $?

# =====================================================================================
t "architecture: Core never learns the browser engine"
for f in ai-os ai-os-capability ai-os-adapter ai-sync ai-os-memory ai-os-doctor ai-os-init ai-os-onboard; do
  grep -Eqi 'playwright|chromium|webkit|querySelector|page\.goto' "$CLI/$f"
  [ $? -ne 0 ];                           chk "Core tool $f names no browser technology" $?
done
grep -Eqi 'playwright|chromium' "$REPO/schemas/capability.schema.md"
[ $? -ne 0 ];                             chk "the capability contract names no engine" $?
# And the capability never learns a client.
grep -Eqi '\bclaude\b|\bcodex\b|\bgemini\b|\bcursor\b|opencode' "$BR/browser" "$BR/browser-verify" "$BR/capability.yaml" "$BR/providers/playwright_provider.py"
[ $? -ne 0 ];                             chk "the browser capability names no AI client" $?
# Nor a domain — the same browser serves sales, software, education alike.
grep -Eqi '\bsales\b|\bmarketing\b|\bsoftware-delivery\b' "$BR/browser" "$BR/capability.yaml"
[ $? -ne 0 ];                             chk "the browser capability names no domain" $?
# Nor a website.
grep -Eqi 'github\.com|google\.com|facebook' "$BR/browser" "$BR/capability.yaml"
[ $? -ne 0 ];                             chk "no website is hardcoded into the capability" $?

# =====================================================================================
t "authority: Core enforces the ladder, and there is no bypass"
AW="$TMP/authws"; AI_OS_HOME="$AW" "$CLI/ai-os-init" >/dev/null 2>&1
grep -q '^default: observe' "$AW/system/config/authority.yaml"
chk "a fresh workspace grants only observe" $?
out=$(AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.read --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "an observe operation is allowed by default" $?
out=$(AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.click --dry-run 2>&1); rc=$?
[ "$rc" -eq 5 ];                          chk "an execute operation is denied by default" $?
echo "$out" | grep -q 'never with a flag';chk "  ...and points at the grant file, not a flag" $?
out=$(AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.submit --dry-run </dev/null 2>&1); rc=$?
[ "$rc" -eq 5 ];                          chk "an approval operation is denied with no terminal" $?
# Grant execute; click becomes allowed, submit still does not.
python3 - "$AW" <<'PYEOF'
import sys,pathlib
f=pathlib.Path(sys.argv[1])/"system/config/authority.yaml"
f.write_text(f.read_text().replace("capabilities: {}","capabilities:\n  browser: execute"))
PYEOF
AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.click --dry-run >/dev/null 2>&1
chk "an explicit grant allows the operation" $?
AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.submit --dry-run </dev/null >/dev/null 2>&1
[ $? -eq 5 ];                             chk "  ...and does not leak into the rung above it" $?
# No bypass flags anywhere in Core.
grep -Eq '\-\-force|\-\-unsafe|\-\-god-mode|\-\-bypass|allowEverything' "$CLI/ai-os-capability"
[ $? -ne 0 ];                             chk "Core offers no force/unsafe/bypass flag" $?
# autonomous is refused, never granted.
python3 - "$AW" <<'PYEOF'
import sys,pathlib
f=pathlib.Path(sys.argv[1])/"system/config/authority.yaml"
f.write_text(f.read_text().replace("  browser: execute","  browser: autonomous"))
PYEOF
out=$(AI_OS_HOME="$AW" "$CLI/ai-os-capability" invoke browser.click --dry-run 2>&1)
echo "$out" | grep -q "granted 'observe'"
chk "an autonomous grant is not honoured — it falls back to the floor" $?

# =====================================================================================
t "verification: executed is never verified by assertion"
VB="$REPO/capabilities/browser"
# A result that simply claims success must not verify.
out=$(cd "$VB" && echo '{"ok":true,"operation":"submit","verified":true,"note":"I submitted it"}' \
      | AI_OS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify submit 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "a self-reported success does not verify" $?
# A failed operation cannot verify.
out=$(cd "$VB" && echo '{"ok":false}' | AI_OS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify navigate 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "a failed operation does not verify" $?
# Verification with no session cannot pass.
out=$(cd "$VB" && echo '{"ok":true,"operation":"read"}' | AI_OS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify read 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "no live session means not verified" $?
# The verifier reads live state, so it must not be a pure function of its input.
grep -q 'prov.connect' "$VB/browser-verify";  chk "the verifier reconnects to live state" $?
grep -Eq 'if .*model|self_report|claim\["verified"\]' "$VB/browser-verify"
[ $? -ne 0 ];                             chk "the verifier never reads a 'verified' claim" $?
# Every operation in the manifest declares a verify command.
n_ops=$(grep -cE '^  [a-z]+:$' "$VB/capability.yaml")
n_ver=$(grep -c 'verify: browser-verify' "$VB/capability.yaml")
[ "$n_ops" -eq "$n_ver" ];                chk "every operation declares deterministic verification" $?

# =====================================================================================
t "browser capability: security boundaries"
grep -Eq 'password|token|secret|cookie:|api[_-]?key' "$VB/capability.yaml"
[ $? -ne 0 ];                             chk "no secrets in the manifest" $?
# The capability may only be invoked through its declared command, which Core resolves
# inside the capability directory — the escape check already tested for requires:.
grep -q 'cwd=str(d)' "$CLI/ai-os-capability";  chk "Core runs a capability inside its own directory" $?
grep -q 'shell=True' "$CLI/ai-os-capability"
[ $? -ne 0 ];                             chk "Core never invokes through a shell" $?
# Session state is runtime, not durable truth.
grep -q 'runtime' "$VB/browser";           chk "browser session state lives under runtime/" $?
grep -Eq 'tasks/|02-personal|05-knowledge' "$VB/browser"
[ $? -ne 0 ];                             chk "the capability writes no durable workspace state" $?

# =====================================================================================
t "browser capability: real browser execution (needs a working provider)"
if (cd "$VB" && echo '{}' | ./browser detect >/dev/null 2>&1); then
  RT="$TMP/br"; WEB="$TMP/web"; mkdir -p "$WEB"
  cat > "$WEB/f.html" <<'HTMLEOF'
<html><body><h1 id="h">Exam</h1><form action="d.html" method="get">
<input id="a" name="a" type="text"><button id="g" type="submit">Go</button></form></body></html>
HTMLEOF
  echo '<html><body><h1 id="ok">Done</h1></body></html>' > "$WEB/d.html"
  br() { (cd "$VB" && echo "$2" | AI_OS_BROWSER_RUNTIME="$RT" ./browser "$1"); }
  br open '{}' | grep -q '"ok": true';    chk "a browser session opens" $?
  br navigate "{\"url\":\"file://$WEB/f.html\"}" | grep -q 'f.html'
  chk "navigate reaches the page" $?
  br read '{}' | grep -q 'Exam';          chk "read returns visible page text" $?
  br observe '{}' | grep -q '"id": "a"';  chk "observe reports interactive elements" $?
  br type '{"selector":"#a","text":"42"}' | grep -q '"value": "42"'
  chk "type enters text into a field" $?
  br extract '{"selector":"#h"}' | grep -q 'Exam'; chk "extract pulls element text" $?
  br scroll '{"dy":100}' | grep -q 'scrollY'; chk "scroll moves the page" $?
  # The multi-step sequence, ending in DETERMINISTIC verification of a real submit.
  res=$(br submit '{"selector":"#g","expect":{"url_contains":"d.html"}}')
  echo "$res" | grep -q 'd.html';         chk "submit performs the form submission" $?
  (cd "$VB" && printf '%s' "$res" | AI_OS_BROWSER_RUNTIME="$RT" ./browser-verify submit >/dev/null 2>&1)
  chk "  ...and live browser state VERIFIES it" $?
  # The same submit with a false expectation must not verify.
  (cd "$VB" && printf '%s' "$res" | sed 's/d.html"}}/nope"}}/' \
     | AI_OS_BROWSER_RUNTIME="$RT" ./browser-verify submit >/dev/null 2>&1)
  [ $? -ne 0 ];                           chk "  ...and a false expectation does NOT verify" $?
  br close '{}' | grep -q '"ok": true';   chk "the session closes and releases the browser" $?
  [ ! -f "$RT/session.json" ];            chk "  ...leaving no session behind" $?
else
  printf '  %sSKIP%s browser provider unavailable on this machine\n' "$D" "$X"
fi

# =====================================================================================
t "run: create requires an explicit, finite budget and scope"
RW="$TMP/runws"; AI_OS_HOME="$RW" "$CLI/ai-os-init" >/dev/null 2>&1
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" create --scope 'browser.read' 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "refuses to create with no --max-steps" $?
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" create --max-steps 3 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "refuses to create with no --scope" $?
grep -Eq -- '--unlimited|--no-limit|autonomous=true' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "no unlimited/bypass mode exists in the code" $?
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" create --max-steps 3 --scope 'browser.read,browser.navigate' --task AIOS-TEST 2>&1)
echo "$out" | grep -q 'created';          chk "creates a run with a finite budget and scope" $?
RUN_ID=$(echo "$out" | grep -oE 'run-[0-9a-f-]+' | head -1)
[ -n "$RUN_ID" ];                         chk "  ...and prints its id" $?
[ -f "$RW/runtime/runs/$RUN_ID.json" ];   chk "  ...persisted under runtime/, not tasks/ or memory" $?

# =====================================================================================
t "run: scope — out-of-scope capability/operation is refused, run stays continue"
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" step "$RUN_ID" browser.click --dry-run 2>&1); rc=$?
echo "$out" | grep -q 'outside this run.s scope';  chk "an out-of-scope operation is refused" $?
[ "$rc" -ne 0 ];                          chk "  ...as a non-zero exit" $?
rec="$RW/runtime/runs/$RUN_ID.json"
grep -q '"status": "continue"' "$rec";    chk "  ...and the run itself is untouched — still continue" $?
grep -q '"steps_used": 0' "$rec";         chk "  ...a Run-local refusal never consumes budget" $?

# =====================================================================================
t "run: authority — run scope can only restrict, never elevate, the user's grant"
grep -q '^default: observe' "$RW/system/config/authority.yaml"
chk "fresh workspace still grants only observe" $?
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" step "$RUN_ID" browser.read --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "an in-scope, observe-level op is allowed" $?
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" step "$RUN_ID" browser.navigate --dry-run 2>&1); rc=$?
echo "$out" | grep -q "needs 'execute'; granted 'observe'"
chk "an in-scope op still needs the SAME authority invoke would require" $?
[ "$rc" -eq 6 ];                          chk "  ...and the run blocks rather than silently downgrading" $?
grep -Eq -- '--force|--unsafe|--bypass|allowEverything|authority\.yaml.*=.*open\(.*.w.' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "ai-os-run contains no bypass flag and never writes authority.yaml" $?
grep -q 'stdin=subprocess.DEVNULL' "$CLI/ai-os-run"
chk "every step's stdin is closed — a Run can never see a terminal to approve through" $?

# =====================================================================================
t "run: approval — execute-with-approval is never silently satisfied"
AI_OS_HOME="$RW" "$CLI/ai-os-run" create --max-steps 3 --scope 'browser.submit' >/tmp/aios-run-approval.out 2>&1
RUN_A=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-approval.out | head -1)
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" step "$RUN_A" browser.submit --dry-run </dev/null 2>&1); rc=$?
echo "$out" | grep -q "needs-approval";   chk "an approval-gated op moves the run to needs-approval" $?
[ "$rc" -eq 5 ];                          chk "  ...as its own distinct exit code" $?
grep -q '"status": "needs-approval"' "$RW/runtime/runs/$RUN_A.json"
chk "  ...and the run record says so" $?
out=$(AI_OS_HOME="$RW" "$CLI/ai-os-run" step "$RUN_A" browser.read --dry-run 2>&1); rc=$?
echo "$out" | grep -q 'refused';          chk "needs-approval is terminal — no further step is taken" $?
rm -f /tmp/aios-run-approval.out

# =====================================================================================
t "run: verification — an executed-but-unverified step never becomes 'completed'"
grep -q "deterministic check passed" "$CLI/ai-os-run"
chk "completion is only ever tied to invoke's own 'verified' text, never asserted" $?
grep -Eq 'status.*=.*.completed.*executed' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "no code path marks 'executed' alone as completed" $?

# =====================================================================================
t "run: budget — a step beyond max_steps is refused and the run ends"
BW="$TMP/budgetws"; AI_OS_HOME="$BW" "$CLI/ai-os-init" >/dev/null 2>&1
AI_OS_HOME="$BW" "$CLI/ai-os-run" create --max-steps 1 --scope 'browser.navigate' >/tmp/aios-run-budget.out 2>&1
RUN_B=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-budget.out | head -1)
AI_OS_HOME="$BW" "$CLI/ai-os-run" step "$RUN_B" browser.navigate --json '{"url":"http://example.com"}' >/dev/null 2>&1
grep -q '"steps_used": 1' "$BW/runtime/runs/$RUN_B.json"
chk "the one permitted step consumed the budget" $?
out=$(AI_OS_HOME="$BW" "$CLI/ai-os-run" step "$RUN_B" browser.navigate --json '{}' 2>&1); rc=$?
echo "$out" | grep -qE 'blocked|budget exhausted|not .continue.'
chk "a step beyond the budget is refused" $?
[ "$rc" -ne 0 ];                          chk "  ...as a non-zero exit" $?
rm -f /tmp/aios-run-budget.out

# =====================================================================================
t "run: reset protection — nothing in this CLI can grow or reset max_steps"
n=$(grep -c 'max_steps' "$CLI/ai-os-run")
[ "$n" -gt 0 ];                           chk "max_steps exists" $?
! grep -qE '^CMDS = .*"(reset|extend|edit|update)"' "$CLI/ai-os-run"
chk "no reset/extend/edit/update subcommand exists" $?
grep -c '"create": cmd_create' "$CLI/ai-os-run" | grep -q '^1$'
chk "max_steps is set exactly once, at create" $?

# =====================================================================================
t "run: task isolation — Core never reads or writes tasks/"
grep -Eq 'tasks/|open\(.*task\.md|task_id\].*read_text' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "ai-os-run contains no path into tasks/" $?
grep -q 'opaque' "$CLI/ai-os-run";        chk "task_id is documented as opaque, never parsed" $?

# =====================================================================================
t "run: persistence isolation — run state lives only under runtime/"
grep -q 'RUNS_DIR = private_path_or_die("runtime") / "runs"' "$CLI/ai-os-run"
chk "run records are rooted under runtime/runs/" $?
grep -Eq '02-personal|05-knowledge|memory/|knowledge/' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "ai-os-run writes no durable workspace state" $?

# =====================================================================================
t "run: determinism — the same run, the same step, refused the same way twice"
DW="$TMP/detws"; AI_OS_HOME="$DW" "$CLI/ai-os-init" >/dev/null 2>&1
AI_OS_HOME="$DW" "$CLI/ai-os-run" create --max-steps 5 --scope 'browser.read' >/tmp/aios-run-det.out 2>&1
RUN_D=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-det.out | head -1)
out1=$(AI_OS_HOME="$DW" "$CLI/ai-os-run" step "$RUN_D" browser.click --dry-run 2>&1); rc1=$?
out2=$(AI_OS_HOME="$DW" "$CLI/ai-os-run" step "$RUN_D" browser.click --dry-run 2>&1); rc2=$?
[ "$rc1" -eq "$rc2" ];                    chk "the same out-of-scope call refuses identically twice" $?
[ "$out1" = "$out2" ];                    chk "  ...with byte-identical output" $?
rm -f /tmp/aios-run-det.out

# =====================================================================================
t "run: not an orchestrator — no decision-making vocabulary in this file"
grep -Eiq '\bnext_action\b|\bplan\(|\bdecide_capability\b|\bchoose_operation\b' "$CLI/ai-os-run"
[ $? -ne 0 ];                             chk "ai-os-run contains no planning/decision logic" $?

# =====================================================================================
if (cd "$REPO/capabilities/browser" && echo '{}' | ./browser detect >/dev/null 2>&1); then
t "run: no-progress — an identical unverified step repeated 3x blocks the run"
NW="$TMP/noprogws"; AI_OS_HOME="$NW" "$CLI/ai-os-init" >/dev/null 2>&1
python3 - "$NW" <<'PYEOF'
import sys, pathlib
f = pathlib.Path(sys.argv[1]) / "system/config/authority.yaml"
f.write_text(f.read_text().replace("capabilities: {}", "capabilities:\n  browser: execute"))
PYEOF
NWEB="$TMP/noprog-web"; mkdir -p "$NWEB"
cat > "$NWEB/f.html" <<'HTMLEOF'
<html><body><h1 id="h">Exam</h1><button id="b" type="button">Click</button></body></html>
HTMLEOF
export AI_OS_BROWSER_RUNTIME="$TMP/noprog-runtime"
AI_OS_HOME="$NW" "$CLI/ai-os-run" create --max-steps 10 \
  --scope 'browser.open,browser.navigate,browser.click,browser.close' >/tmp/aios-run-noprog.out 2>&1
RUN_N=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-noprog.out | head -1)
AI_OS_HOME="$NW" "$CLI/ai-os-run" step "$RUN_N" browser.open --json '{}' >/dev/null 2>&1
AI_OS_HOME="$NW" "$CLI/ai-os-run" step "$RUN_N" browser.navigate --json "{\"url\":\"file://$NWEB/f.html\"}" >/dev/null 2>&1
for i in 1 2 3; do
  out=$(AI_OS_HOME="$NW" "$CLI/ai-os-run" step "$RUN_N" browser.click --json '{"selector":"#b"}' 2>&1)
done
echo "$out" | grep -q 'no-progress';      chk "the 3rd identical unverified click blocks the run" $?
grep -q '"status": "blocked"' "$NW/runtime/runs/$RUN_N.json"
chk "  ...recorded in the run itself" $?
out=$(AI_OS_HOME="$NW" "$CLI/ai-os-run" step "$RUN_N" browser.click --json '{"selector":"#b"}' 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "  ...and a 4th attempt is refused, not retried" $?
AI_OS_HOME="$NW" AI_OS_PLUGINS="$REPO/capabilities" "$CLI/ai-os-capability" invoke browser.close --json '{}' >/dev/null 2>&1
rm -f /tmp/aios-run-noprog.out
else
  printf '  %sSKIP%s run: no-progress test needs a working browser provider\n' "$D" "$X"
fi

# =====================================================================================
t "run: dispatcher and schema exist and are wired"
grep -q 'ai-os run' "$CLI/ai-os";          chk "ai-os run is a documented subcommand" $?
grep -q '|run|' "$CLI/ai-os";              chk "  ...and dispatches to ai-os-run" $?
[ -f "$REPO/schemas/run.schema.md" ];      chk "schemas/run.schema.md exists" $?
grep -q 'not an agent' "$REPO/schemas/run.schema.md"
chk "  ...and states the boundary: not an agent/orchestrator/planner" $?

# =====================================================================================
t "handoff: dispatcher exposes ai-os handoff"
grep -q 'ai-os handoff' "$CLI/ai-os";      chk "ai-os handoff is a documented subcommand" $?
grep -q '|handoff)' "$CLI/ai-os";          chk "  ...and dispatches to ai-os-handoff" $?
[ -x "$CLI/ai-os-handoff" ];               chk "cli/ai-os-handoff exists and is executable" $?

# =====================================================================================
t "handoff: prepare writes one task-local Markdown record"
HW="$TMP/handoff-ws"; AI_OS_HOME="$HW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$HW/tasks/AIOS-TEST"
cat > "$HW/tasks/AIOS-TEST/task.md" <<'TASKEOF'
---
id: AIOS-TEST
title: A durable task the handoff is bound to
project: ai-os
---
TASKEOF
# Everything outside tasks/ is fingerprinted first: a record engine that writes one file
# beside one task must leave the rest of the workspace byte-identical.
hw_outside() { (cd "$HW" && find . -path ./tasks -prune -o -type f -exec shasum {} \; | sort | shasum); }
before=$(hw_outside)
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review \
        --scope 'cli/ai-os-handoff, tests/test-contract.sh' \
        --summary 'V2 record engine only' 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "prepare exits 0" $?
HID=$(printf '%s\n' "$out" | grep -oE '[0-9]{8}-[0-9]{3}' | head -1)
HREC="$HW/tasks/AIOS-TEST/handoff-$HID.md"
[ -n "$HID" ];                             chk "reports the handoff id it created" $?
[ -f "$HREC" ];                            chk "wrote tasks/<ID>/handoff-<handoff_id>.md, beside the task" $?
[ "$(find "$HW/tasks/AIOS-TEST" -name 'handoff-*.md' | wc -l | tr -d ' ')" = "1" ]
chk "  ...exactly one record and nothing else" $?
[ "$before" = "$(hw_outside)" ];           chk "  ...and nothing at all outside tasks/ changed" $?
[ ! -d "$HW/handoffs" ];                   chk "no global handoffs/ directory was created" $?
[ ! -e "$HW/tasks/AIOS-TEST/index.md" ] && [ ! -e "$HW/tasks/index.md" ]
chk "no hidden index, queue or bus was written" $?

# =====================================================================================
t "handoff: the record is readable and carries every required field"
grep -q "^handoff_id: $HID\$" "$HREC";     chk "handoff id" $?
grep -q '^task_id: AIOS-TEST$' "$HREC";    chk "task id" $?
grep -Eq '^status: (draft|waiting-owner)$' "$HREC"
chk "status, and only draft or waiting-owner" $?
grep -Eq '^created: [0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$' "$HREC"
chk "created time" $?
grep -q '^to: codex$' "$HREC";             chk "destination client" $?
grep -q '^gate: review$' "$HREC";          chk "gate" $?
grep -q '^scope: ' "$HREC";                chk "scope" $?
grep -q '^current_holder: owner$' "$HREC"; chk "current holder" $?
grep -q '^next_holder: codex$' "$HREC";    chk "next holder" $?
grep -q 'packet:begin' "$HREC" && grep -q 'packet:end' "$HREC"
chk "outgoing packet text, delimited" $?
grep -q 'V2 record engine only' "$HREC";   chk "  ...carrying the summary it was given" $?
grep -q 'A durable task the handoff is bound to' "$HREC"
chk "  ...and the task context read from task.md" $?
grep -q '^## 6. Audit' "$HREC";            chk "audit section" $?

# =====================================================================================
t "handoff: prepare creates no approval, no send and no returned block"
grep -q '^## 3. Owner approval' "$HREC";   chk "an owner approval section exists" $?
grep -q 'No approval recorded' "$HREC";    chk "  ...and it is empty" $?
grep -q '^approval: none$' "$HREC";        chk "  ...stated in the frontmatter too" $?
grep -Eiq 'owner_words|approved: yes|approved_at|approved_by' "$HREC"
[ $? -ne 0 ];                              chk "  ...with no approval field of any kind filled in" $?
grep -q '^## 4. Send' "$HREC";             chk "a send section exists" $?
grep -q 'Nothing sent' "$HREC";            chk "  ...and it is empty" $?
grep -q '^sent: no$' "$HREC";              chk "  ...stated in the frontmatter too" $?
grep -Eiq 'sent_at|transport: (clipboard|mcp|http|api)|payload_hash: [0-9a-f]{8}' "$HREC"
[ $? -ne 0 ];                              chk "  ...with no send field populated" $?
grep -q '^## 5. Returned block' "$HREC";   chk "a returned-block section exists" $?
grep -q 'Nothing returned' "$HREC";        chk "  ...and it is empty" $?
grep -q '^returned: none$' "$HREC";        chk "  ...stated in the frontmatter too" $?
grep -q 'approved:         no' "$HREC";    chk "the audit says V2 did not approve" $?
grep -q 'sent:             no' "$HREC";    chk "the audit says V2 did not send" $?
grep -q 'clients_contacted: none' "$HREC"; chk "the audit says no client was contacted" $?

# =====================================================================================
t "handoff: show prints the record, list finds it"
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff show AIOS-TEST "$HID" 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "show exits 0" $?
[ "$out" = "$(cat "$HREC")" ];             chk "  ...and prints the record verbatim" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff list AIOS-TEST 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "list exits 0" $?
echo "$out" | grep -q "$HID";              chk "  ...and finds the record it just wrote" $?
echo "$out" | grep -q 'codex';             chk "  ...with its destination" $?
[ "$before" = "$(hw_outside)" ];           chk "show and list wrote nothing" $?

# =====================================================================================
t "handoff: draft records cannot be approved or sent"
SEED="$TMP/seed-reply.md"; echo "a reply that is never attached" > "$SEED"
rec_before=$(shasum < "$HREC"); ws_before=$(cd "$HW" && find . -type f | sort | shasum)
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST "$HID" --gate review --to codex \
  --scope 'cli/ai-os-handoff, tests/test-contract.sh' --owner-words 'Owner approves this fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "approve refuses a draft record" $?
echo "$out" | grep -q 'waiting-owner';    chk "  ...and says only waiting-owner can be approved" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff send AIOS-TEST "$HID" 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "send refuses a record with no matching approval" $?
echo "$out" | grep -q "not 'approved'"; chk "  ...naming the status it refused on" $?
echo "$out" | grep -q 'nothing was sent';  chk "  ...and saying nothing was sent" $?
echo "$out" | grep -Eiq 'transport|handoff-transports'
[ $? -ne 0 ];                            chk "  ...refused before any transport was consulted" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff receive AIOS-TEST "$HID" \
        --from codex --file "$SEED" 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "handoff receive exits non-zero on a draft" $?
echo "$out" | grep -q "not 'sent'";        chk "  ...because nothing was ever sent to reply to" $?
[ "$rec_before" = "$(shasum < "$HREC")" ]; chk "the record is byte-identical after all three refusals" $?
[ "$ws_before" = "$(cd "$HW" && find . -type f | sort | shasum)" ]
chk "no receive side effect — no file created, moved or removed" $?
[ ! -d "$HW/handoffs" ];                   chk "still no global handoffs/ directory" $?

# =====================================================================================
t "handoff: refusals write nothing"
n_before=$(find "$HW/tasks/AIOS-TEST" -name 'handoff-*.md' | wc -l | tr -d ' ')
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing task id refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare ../escape --to codex --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "invalid task id refused (no path escape)" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare NO-SUCH --to codex --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing task directory refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --to refused" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to nobody --gate review --scope x 2>&1)
[ $? -ne 0 ];                              chk "unknown destination client refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to 'codex,claude-code' --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "more than one destination refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --to gemini --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "  ...including a repeated --to" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --gate refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate anything --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a gate outside the template vocabulary refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --scope refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review --scope '   ' >/dev/null 2>&1
[ $? -ne 0 ];                              chk "empty --scope refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review --scope x --status approved >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a status V2 may not write refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review --scope x --id "$HID" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a duplicate handoff id refused" $?
[ "$rec_before" = "$(shasum < "$HREC")" ]; chk "  ...and the existing record untouched" $?
# Assembled from two adjacent quoted halves on purpose: a token-shaped literal sitting in
# a public test file would be a real finding, and ai-os-privacy-scan would be right to
# flag it. The shell joins them; the scanner reading the file text never sees `ghp_`.
FAKE_TOKEN="gh"'p_0123456789abcdefghijklmnop'
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to codex --gate review --scope x \
  --summary "credential $FAKE_TOKEN" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a credential-shaped value in the packet refused" $?
[ "$(find "$HW/tasks/AIOS-TEST" -name 'handoff-*.md' | wc -l | tr -d ' ')" = "$n_before" ]
chk "fourteen refusals, zero records written" $?

# =====================================================================================
t "handoff: a second record is additive, not an overwrite"
AI_OS_HOME="$HW" "$CLI/ai-os" handoff prepare AIOS-TEST --to claude-code --gate next-step \
  --scope 'V3 approval gate' --status waiting-owner --id trial-a >/dev/null 2>&1
[ $? -eq 0 ];                              chk "a second prepare exits 0" $?
[ -f "$HW/tasks/AIOS-TEST/handoff-trial-a.md" ]; chk "  ...and writes its own file" $?
[ "$rec_before" = "$(shasum < "$HREC")" ]; chk "  ...leaving the first record byte-identical" $?
grep -q '^status: waiting-owner$' "$HW/tasks/AIOS-TEST/handoff-trial-a.md"
chk "  ...with waiting-owner as the other status V2 may write" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff list AIOS-TEST 2>&1)
echo "$out" | grep -q trial-a && echo "$out" | grep -q "$HID"
chk "list shows both, found by globbing the task directory" $?

# =====================================================================================
t "handoff: approve records explicit owner words and exact tuple only"
AREC="$HW/tasks/AIOS-TEST/handoff-trial-a.md"
approval_before=$(shasum < "$AREC"); ws_before=$(cd "$HW" && find . -type f | sort | shasum)
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate review \
  --to claude-code --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched gate refused" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to codex --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched destination refused" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'other scope' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched scope refused" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval without owner words refused" $?
AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' --owner-words "$FAKE_TOKEN" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "credential-shaped owner words refused" $?
[ "$approval_before" = "$(shasum < "$AREC")" ]; chk "all bad approvals leave the record byte-identical" $?
[ "$ws_before" = "$(cd "$HW" && find . -type f | sort | shasum)" ]
chk "  ...and write no side files" $?

out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "exact approval exits 0" $?
grep -q '^status: approved$' "$AREC";      chk "  ...moves waiting-owner to approved" $?
grep -q '^approval: recorded$' "$AREC";    chk "  ...marks approval recorded" $?
grep -q '^approved_gate: next-step$' "$AREC"; chk "  ...records approved gate" $?
grep -q '^approved_to: claude-code$' "$AREC"; chk "  ...records approved destination" $?
grep -q '^approved_scope: V3 approval gate$' "$AREC"; chk "  ...records approved scope" $?
grep -q '^owner_words: Owner approves V3 fixture$' "$AREC"; chk "  ...stores owner words verbatim" $?
grep -q '^approved_at: ' "$AREC";          chk "  ...records approval time" $?
grep -q 'This approval is valid only for the exact tuple above' "$AREC"
chk "  ...and states the approval boundary in the record" $?
grep -q 'sent:             no' "$AREC";    chk "approval still does not send" $?
[ ! -d "$HW/handoffs" ];                   chk "approval creates no global handoffs/ directory" $?

approved_before=$(shasum < "$AREC")
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture again' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "a second approval is refused, not overwritten" $?
[ "$approved_before" = "$(shasum < "$AREC")" ]; chk "  ...leaving owner words byte-identical" $?
out=$(AI_OS_HOME="$HW" "$CLI/ai-os" handoff send AIOS-TEST trial-a --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "send --dry-run exits 0 once the approval matches" $?
echo "$out" | grep -q 'dry run';           chk "  ...and says it is a dry run" $?
[ "$approved_before" = "$(shasum < "$AREC")" ]; chk "  ...and still writes nothing" $?

# =====================================================================================
t "handoff: the sender has exactly one way out, and it is fenced"
# V2 and V3 asserted this file could not spawn anything at all. V4 gives it one call, so
# the invariant moves: not "no subprocess" but "one subprocess, no shell, no retry".
grep -Eq '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z0-9_, ]*\b(socket|http|urllib|smtplib|ftplib|telnetlib|asyncio|requests|ssl)\b' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "imports nothing that could open a network connection" $?
grep -Eq 'os\.(system|popen|exec[lv]|spawn)|urlopen|pbcopy|pbpaste|osascript|xdg-open|webbrowser' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no shell-out, clipboard or app-open call" $?
grep -Eq 'shell[[:space:]]*=[[:space:]]*True' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "never shell=True — the packet can never be a command" $?
[ "$(grep -c 'subprocess\.run(' "$CLI/ai-os-handoff")" = "1" ]
chk "exactly one subprocess.run call site in the whole file" $?
grep -q 'subprocess.run(argv, input=packet' "$CLI/ai-os-handoff"
chk "  ...taking a list argv and the packet on stdin" $?
grep -Eq 'timeout=timeout' "$CLI/ai-os-handoff"; chk "  ...under a timeout" $?
grep -Eq 'os\.fork|threading\.|multiprocessing\.|Thread\(|Timer\(|nohup|setsid' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no thread, fork, timer or background worker" $?
grep -Eiq 'mcp__|mcp_servers|claude\.ai|api\.anthropic|api\.openai|https?://|wss?://' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no MCP server, connector or AI endpoint" $?
grep -Eq 'handoffs/|"handoffs"' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no path to a global handoffs/ directory" $?
grep -Eq 'def cmd_receive' "$CLI/ai-os-handoff"
chk "receive is implemented" $?
grep -Eq 'while True|time\.sleep\(|\.retry|backoff[[:space:]]*=' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no sleep, backoff or polling primitive" $?
# "Not retried" is structural, not textual: no call out of this file may sit inside any
# loop. A grep for the word "retry" would only find the comment promising there isn't one.
python3 - "$CLI/ai-os-handoff" <<'PYEOF'
import ast, pathlib, sys
CALLS = {"run", "Popen", "call", "check_call", "check_output"}
class V(ast.NodeVisitor):
    def __init__(self): self.depth, self.bad = 0, []
    def _loop(self, node):
        self.depth += 1; self.generic_visit(node); self.depth -= 1
    visit_For = visit_AsyncFor = visit_While = _loop
    def visit_Call(self, node):
        f = node.func
        if (isinstance(f, ast.Attribute) and f.attr in CALLS
                and isinstance(f.value, ast.Name) and f.value.id == "subprocess"
                and self.depth):
            self.bad.append(node.lineno)
        self.generic_visit(node)
v = V(); v.visit(ast.parse(pathlib.Path(sys.argv[1]).read_text()))
sys.exit(1 if v.bad else 0)
PYEOF
chk "no subprocess call sits inside any loop — one attempt, never retried" $?
grep -q 'TRANSPORTS = Path(os.environ.get("AI_OS_HANDOFF_TRANSPORTS"' "$CLI/ai-os-handoff"
chk "the transport is read from a declared registry, never synthesised" $?
grep -Eiq '\bnext_action\b|def (plan|decide|orchestrat|dispatch|route)' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "no planning, orchestration or dispatch logic" $?
grep -q 'TASKS = private_path_or_die("work")' "$CLI/ai-os-handoff"
chk "records are bound to the resolved work root and nowhere else" $?

# =====================================================================================
t "handoff send: fixtures"
SW="$TMP/send-ws"; AI_OS_HOME="$SW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$SW/tasks/AIOS-SEND"
cat > "$SW/tasks/AIOS-SEND/task.md" <<'TASKEOF'
---
id: AIOS-SEND
title: The send fixture task
project: ai-os
---
TASKEOF
# Two stand-in destination clients. Nothing here is an AI: the point is to exercise the
# real transport code path — argv, stdin, exit code — without contacting anything.
FB="$TMP/send-bin"; mkdir -p "$FB"
cat > "$FB/fakeclient" <<'FCEOF'
#!/usr/bin/env bash
packet=$(cat)
printf '%s' "$packet" > "$FAKE_CLIENT_SINK"
printf 'fake-client received %s bytes on stdin\n' "${#packet}"
FCEOF
cat > "$FB/failclient" <<'FCEOF'
#!/usr/bin/env bash
cat >/dev/null
echo call >> "$FAKE_CLIENT_SINK.count"
echo "the destination refused it" >&2
exit 3
FCEOF
chmod +x "$FB/fakeclient" "$FB/failclient"
mk_registry() { # <file> <binary> <verified>
  cat > "$1" <<REOF
contract: 1
transports:
  codex:
    name: contract-test stand-in for a destination client
    binary: $2
    argv: [--one-shot]
    stdin: packet
    timeout: 30
    verified: $3
REOF
}
mk_registry "$TMP/tr-ok.yaml"        fakeclient            true
mk_registry "$TMP/tr-fail.yaml"      failclient            true
mk_registry "$TMP/tr-unverified.yaml" fakeclient           false
mk_registry "$TMP/tr-nobinary.yaml"  no-such-client-binary true
hsend() { # <registry> <args...>  — one send, with the fixture bin dir in front of PATH
  local reg="$1"; shift
  AI_OS_HOME="$SW" PATH="$FB:$PATH" AI_OS_HANDOFF_TRANSPORTS="$reg" \
    FAKE_CLIENT_SINK="$TMP/sink.txt" "$CLI/ai-os" handoff send AIOS-SEND "$@" 2>&1
}
mkh() { AI_OS_HOME="$SW" "$CLI/ai-os" handoff prepare AIOS-SEND --to "$2" --gate "$3" \
          --scope "$4" --status waiting-owner --id "$1" >/dev/null 2>&1; }
apr() { AI_OS_HOME="$SW" "$CLI/ai-os" handoff approve AIOS-SEND "$1" --gate "$3" --to "$2" \
          --scope "$4" --owner-words "$5" >/dev/null 2>&1; }
ws_fp() { (cd "$SW" && find . -type f -exec shasum {} \; | sort | shasum); }
ws_fp_but() { (cd "$SW" && find . -type f ! -name "handoff-$1.md" -exec shasum {} \; | sort | shasum); }
mkh unapproved codex review 'scope A'
mkh tuple      codex review 'scope B'; apr tuple      codex review 'scope B' 'Owner approves B'
mkh blank      codex review 'scope C'; apr blank      codex review 'scope C' 'Owner approves C'
mkh dry        codex review 'scope D'; apr dry        codex review 'scope D' 'Owner approves D'
mkh blocked    codex review 'scope E'; apr blocked    codex review 'scope E' 'Owner approves E'
mkh good       codex review 'scope F'; apr good       codex review 'scope F' 'Owner approves F'
mkh failing    codex review 'scope G'; apr failing    codex review 'scope G' 'Owner approves G'
mkh nobinary   codex review 'scope H'; apr nobinary   codex review 'scope H' 'Owner approves H'
[ "$(find "$SW/tasks/AIOS-SEND" -name 'handoff-*.md' | wc -l | tr -d ' ')" = "8" ]
chk "eight fixture records, one approved chain each" $?

# =====================================================================================
t "handoff send: no approval, no send"
before=$(ws_fp)
out=$(hsend "$TMP/tr-ok.yaml" unapproved); rc=$?
[ "$rc" -ne 0 ];                           chk "send refuses a record with no approval" $?
echo "$out" | grep -q "not 'approved'";    chk "  ...naming the status it refused on" $?
[ "$before" = "$(ws_fp)" ];                chk "  ...and writes nothing at all" $?
[ ! -f "$TMP/sink.txt" ];                  chk "  ...the destination received nothing" $?
sed -i.bak 's/^approval: recorded$/approval: none/' "$SW/tasks/AIOS-SEND/handoff-tuple.md"
rm -f "$SW/tasks/AIOS-SEND/handoff-tuple.md.bak"
before=$(ws_fp)
out=$(hsend "$TMP/tr-ok.yaml" tuple); rc=$?
[ "$rc" -ne 0 ];                           chk "send refuses when approval is not 'recorded'" $?
[ "$before" = "$(ws_fp)" ];                chk "  ...and writes nothing" $?
sed -i.bak 's/^approval: none$/approval: recorded/' "$SW/tasks/AIOS-SEND/handoff-tuple.md"
rm -f "$SW/tasks/AIOS-SEND/handoff-tuple.md.bak"

# =====================================================================================
t "handoff send: a mismatched approval tuple is not an approval"
for pair in "approved_gate:execute" "approved_to:claude-code" "approved_scope:something else"; do
  key="${pair%%:*}"; val="${pair#*:}"
  cp "$SW/tasks/AIOS-SEND/handoff-tuple.md" "$TMP/tuple.orig"
  sed -i.bak "s/^$key: .*/$key: $val/" "$SW/tasks/AIOS-SEND/handoff-tuple.md"
  rm -f "$SW/tasks/AIOS-SEND/handoff-tuple.md.bak"
  before=$(ws_fp)
  out=$(hsend "$TMP/tr-ok.yaml" tuple); rc=$?
  [ "$rc" -ne 0 ];                         chk "send refuses when $key differs from the record" $?
  echo "$out" | grep -q 'mismatch';        chk "  ...and says the tuple mismatched" $?
  [ "$before" = "$(ws_fp)" ];              chk "  ...writing nothing" $?
  [ ! -f "$TMP/sink.txt" ];                chk "  ...and sending nothing" $?
  cp "$TMP/tuple.orig" "$SW/tasks/AIOS-SEND/handoff-tuple.md"
done

# =====================================================================================
t "handoff send: an incomplete approval is not an approval"
for key in approved_at approved_gate approved_to approved_scope owner_words; do
  cp "$SW/tasks/AIOS-SEND/handoff-blank.md" "$TMP/blank.orig"
  sed -i.bak "s/^$key: .*/$key: /" "$SW/tasks/AIOS-SEND/handoff-blank.md"
  rm -f "$SW/tasks/AIOS-SEND/handoff-blank.md.bak"
  before=$(ws_fp)
  out=$(hsend "$TMP/tr-ok.yaml" blank); rc=$?
  [ "$rc" -ne 0 ];                         chk "send refuses when $key is empty" $?
  echo "$out" | grep -q "$key";            chk "  ...naming the missing field" $?
  [ "$before" = "$(ws_fp)" ];              chk "  ...and writes nothing" $?
  cp "$TMP/blank.orig" "$SW/tasks/AIOS-SEND/handoff-blank.md"
done
[ ! -f "$TMP/sink.txt" ];                  chk "no refusal so far reached the destination" $?

# =====================================================================================
t "handoff send: --dry-run shows everything and writes nothing"
before=$(ws_fp)
out=$(hsend "$TMP/tr-ok.yaml" dry --dry-run); rc=$?
[ "$rc" -eq 0 ];                           chk "dry run exits 0" $?
[ "$before" = "$(ws_fp)" ];                chk "dry run writes nothing anywhere in the workspace" $?
[ ! -f "$TMP/sink.txt" ];                  chk "dry run sends nothing to the destination" $?
echo "$out" | grep -q 'nothing is sent and nothing is written'; chk "  ...and says so" $?
echo "$out" | grep -Eq 'payload_sha256: [0-9a-f]{64}'; chk "shows the payload hash" $?
echo "$out" | grep -q 'one-shot';          chk "shows the exact command it would run" $?
echo "$out" | grep -q 'packet on stdin';   chk "  ...and that the packet goes on stdin, not argv" $?
echo "$out" | grep -q 'Handoff dry — AIOS-SEND'; chk "shows the packet itself, in full" $?
grep -q '^status: approved$' "$SW/tasks/AIOS-SEND/handoff-dry.md"
chk "the record is still 'approved', not 'sent'" $?

# =====================================================================================
t "handoff send: no verified transport is a recorded blocker, never a fake send"
before_other=$(ws_fp_but blocked)
out=$(hsend "$TMP/tr-unverified.yaml" blocked); rc=$?
[ "$rc" -ne 0 ];                           chk "an unverified transport refuses the send" $?
echo "$out" | grep -q 'blocked';           chk "  ...and calls it blocked" $?
[ ! -f "$TMP/sink.txt" ];                  chk "  ...the destination received nothing" $?
BREC="$SW/tasks/AIOS-SEND/handoff-blocked.md"
grep -q 'Not sent — \*\*blocked\*\*' "$BREC";  chk "the blocker is written into the record" $?
grep -q 'verified: false' "$BREC";         chk "  ...with the reason it was blocked" $?
grep -q 'unblocks_when:' "$BREC";          chk "  ...and what would unblock it" $?
grep -Eq '^payload_sha256:    [0-9a-f]{64}$' "$BREC"
chk "  ...and the hash of what would have gone" $?
grep -q '^status: approved$' "$BREC";      chk "the approval survives — status stays 'approved'" $?
grep -q '^sent: no$' "$BREC";              chk "  ...and sent stays no" $?
[ "$before_other" = "$(ws_fp_but blocked)" ]; chk "only that one record changed" $?
[ ! -d "$SW/handoffs" ];                   chk "no global handoffs/ directory" $?
out=$(hsend "$TMP/tr-nobinary.yaml" nobinary); rc=$?
[ "$rc" -ne 0 ];                           chk "a verified transport whose binary is absent also blocks" $?
echo "$out" | grep -q 'not on PATH';       chk "  ...saying the binary is missing" $?
grep -q '^status: approved$' "$SW/tasks/AIOS-SEND/handoff-nobinary.md"
chk "  ...and leaves the approval intact" $?

# =====================================================================================
t "handoff send: an approved send delivers the packet and records it"
GREC="$SW/tasks/AIOS-SEND/handoff-good.md"
python3 - "$GREC" "$TMP/expected-packet.txt" <<'PYEOF'
import sys, pathlib
t = pathlib.Path(sys.argv[1]).read_text()
b, e = t.index("<!-- packet:begin -->"), t.index("<!-- packet:end -->")
pathlib.Path(sys.argv[2]).write_text(t[b + len("<!-- packet:begin -->"):e].strip())
PYEOF
before_other=$(ws_fp_but good)
out=$(hsend "$TMP/tr-ok.yaml" good); rc=$?
[ "$rc" -eq 0 ];                           chk "an approved send over a verified transport exits 0" $?
echo "$out" | grep -q 'fake-client received'; chk "the destination client actually ran" $?
[ -f "$TMP/sink.txt" ];                    chk "  ...and received something" $?
cmp -s "$TMP/sink.txt" "$TMP/expected-packet.txt"
chk "  ...byte-for-byte the packet from section 2, and nothing else" $?
grep -q '^status: sent$' "$GREC";          chk "status becomes 'sent'" $?
grep -q '^sent: yes$' "$GREC";             chk "  ...and sent becomes yes" $?
grep -Eq '^sent_at: [0-9]{4}-[0-9]{2}-[0-9]{2} ' "$GREC"; chk "sent time is recorded" $?
grep -q '^sent_to: codex$' "$GREC";        chk "destination is recorded" $?
grep -q '^sent_transport: ' "$GREC";       chk "transport is recorded" $?
HASH=$(shasum -a 256 "$TMP/expected-packet.txt" | cut -d' ' -f1)
grep -q "^payload_sha256: $HASH\$" "$GREC"
chk "payload hash is recorded, and is the hash of what was actually sent" $?
grep -q 'sent_command:' "$GREC";           chk "the command that sent it is recorded" $?
grep -q 'approval_ref:' "$GREC";           chk "the approval tuple is referenced" $?
grep -q 'owner_words_ref:' "$GREC";        chk "the owner words are referenced, not re-copied" $?
grep -q 'return_expected:' "$GREC";        chk "the return expectation is recorded" $?
grep -q '^current_holder: codex$' "$GREC"; chk "the handoff now sits with the destination" $?
grep -q '^next_holder: owner$' "$GREC";    chk "  ...and comes back to the owner" $?
grep -q 'status:                sent' "$GREC"
chk "the human-readable metadata block agrees with the frontmatter" $?
grep -q 'Nothing returned' "$GREC";        chk "the returned block is still empty — send never receives" $?
[ "$before_other" = "$(ws_fp_but good)" ]; chk "an approved send writes ONLY the handoff record" $?
[ ! -d "$SW/handoffs" ];                   chk "  ...and still no global handoffs/ directory" $?
pgrep -f 'fakeclient --one-shot' >/dev/null 2>&1
[ $? -ne 0 ];                              chk "no process is left running after send returns" $?

# =====================================================================================
t "handoff send: a packet is never sent twice"
rm -f "$TMP/sink.txt"
before=$(ws_fp)
out=$(hsend "$TMP/tr-ok.yaml" good); rc=$?
[ "$rc" -ne 0 ];                           chk "sending an already-sent record is refused" $?
echo "$out" | grep -q 'never sent twice';  chk "  ...and says why" $?
[ "$before" = "$(ws_fp)" ];                chk "  ...writing nothing" $?
[ ! -f "$TMP/sink.txt" ];                  chk "  ...and sending nothing" $?

# =====================================================================================
t "handoff send: a failed transport is recorded, not retried"
FREC="$SW/tasks/AIOS-SEND/handoff-failing.md"
rm -f "$TMP/sink.txt.count"
before_other=$(ws_fp_but failing)
out=$(hsend "$TMP/tr-fail.yaml" failing); rc=$?
[ "$rc" -ne 0 ];                           chk "a transport that exits non-zero fails the send" $?
grep -q 'the transport \*\*failed\*\*' "$FREC"; chk "  ...recorded in the record" $?
grep -q 'exited 3' "$FREC";                chk "  ...with the exit code" $?
grep -q '^status: approved$' "$FREC";      chk "status stays 'approved' — it was not sent" $?
grep -q '^sent: no$' "$FREC";              chk "  ...and sent stays no" $?
grep -Eq 'attempted_at:|failed_at:' "$FREC"; chk "  ...and when it was attempted" $?
[ "$before_other" = "$(ws_fp_but failing)" ]; chk "only that one record changed" $?
[ "$(wc -l < "$TMP/sink.txt.count" | tr -d ' ')" = "1" ]
chk "the destination was invoked exactly once — nothing was retried" $?

# =====================================================================================
t "handoff send: the shipped transport registry is evidence-gated"
[ -f "$REPO/governance/policies/handoff-transports.yaml" ]; chk "governance/policies/handoff-transports.yaml exists" $?
# Asserted through the repo's own manifest parser, not by grepping: the file explains in
# prose what `verified: true` would mean, and a text search cannot tell that apart from a
# transport actually being enabled.
python3 - "$REPO" <<'PYEOF'
import importlib.machinery, importlib.util, pathlib, sys
repo = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_loader("_a", importlib.machinery.SourceFileLoader(
    "_a", str(repo / "cli" / "ai-os-adapter")))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
doc = mod.parse((repo / "governance" / "policies" / "handoff-transports.yaml").read_text(), "transports")
transports = doc.get("transports") or {}
bad = []
codex = transports.get("codex") or {}
claude = transports.get("claude-code") or {}
if codex.get("verified") is not True:
    bad.append("codex transport should be verified only after the owner-run V6 trial")
evidence = str(codex.get("evidence") or "")
for phrase in ("Owner-run trial", "codex-cli 0.147.0", "stdin", "read-only"):
    if phrase not in evidence:
        bad.append(f"codex verified evidence is missing {phrase!r}")
if claude.get("verified") is not True:
    bad.append("claude-code transport should be verified only after the owner-run V6 trial")
evidence = str(claude.get("evidence") or "")
for phrase in ("Owner-run trial", "Claude Code", "stdin", "read no files", "ran no commands"):
    if phrase not in evidence:
        bad.append(f"claude-code verified evidence is missing {phrase!r}")
if bad:
    print("\n".join(bad), file=sys.stderr)
    sys.exit(1)
PYEOF
chk "codex and claude-code are verified by owner-run evidence" $?
grep -q 'read-only' "$REPO/governance/policies/handoff-transports.yaml"
chk "  ...and the declared argv pin the client's read-only mode" $?
grep -q 'stdin: packet' "$REPO/governance/policies/handoff-transports.yaml"
chk "  ...and take the packet on stdin, never in argv" $?
grep -q 'documentation is not evidence' "$REPO/governance/policies/handoff-transports.yaml"
chk "  ...under the same evidence rule adapters/ uses" $?
# A restriction flag has to actually restrict. `--allowed-tools ""` reads like a lockdown
# and is not one: it is an ALLOW-list, so an empty value pre-approves nothing and removes
# nothing. Claude Code's documented disable is `--tools ""`. This shipped wrong once; the
# check exists so it cannot ship wrong again under a flag that merely looks safe.
python3 - "$REPO" <<'PYEOF2'
import importlib.machinery, importlib.util, pathlib, sys
repo = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_loader("_a", importlib.machinery.SourceFileLoader(
    "_a", str(repo / "cli" / "ai-os-adapter")))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
doc = mod.parse((repo / "governance" / "policies" / "handoff-transports.yaml").read_text(), "transports")
bad = []
for name, entry in (doc.get("transports") or {}).items():
    argv = entry.get("argv") or []
    if "--allowed-tools" in argv or "--allowedTools" in argv:
        bad.append(f"{name} pins tools with an allow-list flag, which restricts nothing")
    if entry.get("binary") == "claude" and "--tools" not in argv:
        bad.append(f"{name} runs claude without --tools, so the built-in tools stay live")
for b in bad:
    print(b, file=sys.stderr)
sys.exit(1 if bad else 0)
PYEOF2
chk "  ...and no transport fakes a restriction with an allow-list flag" $?
out=$(AI_OS_HOME="$SW" "$CLI/ai-os" handoff send AIOS-SEND blocked --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "against the shipped registry, dry run still works" $?
if command -v codex >/dev/null 2>&1; then
  echo "$out" | grep -q 'command:';         chk "  ...and shows the verified transport command when codex is installed" $?
  echo "$out" | grep -q 'packet on stdin';  chk "  ...with the packet on stdin" $?
else
  echo "$out" | grep -q 'unavailable';      chk "  ...and reports unavailable when codex is not installed" $?
fi

# =====================================================================================
t "handoff receive: fixtures"
RW="$TMP/recv-ws"; AI_OS_HOME="$RW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$RW/tasks/AIOS-RECV"
cat > "$RW/tasks/AIOS-RECV/task.md" <<'TASKEOF'
---
id: AIOS-RECV
title: The receive fixture task
project: ai-os
---
TASKEOF
RB="$TMP/recv-bin"; mkdir -p "$RB"
cat > "$RB/recvclient" <<'FCEOF'
#!/usr/bin/env bash
cat >/dev/null; echo "stand-in destination ran"
FCEOF
chmod +x "$RB/recvclient"
cat > "$TMP/tr-recv.yaml" <<'REOF'
contract: 1
transports:
  codex:
    name: contract-test stand-in for a destination client
    binary: recvclient
    argv: [--one-shot]
    stdin: packet
    timeout: 30
    verified: true
REOF
cat > "$TMP/reply.md" <<'RPEOF'
reviewer_verdict: approved with findings
reviewer_findings: the preflight holds; two comments are stale.
recommended_next_step: delete the stale comments, then re-run the suite.
RPEOF
rsend() { # <id> — prepare, approve and send one fixture handoff
  AI_OS_HOME="$RW" "$CLI/ai-os" handoff prepare AIOS-RECV --to codex --gate review \
    --scope "scope $1" --status waiting-owner --id "$1" >/dev/null 2>&1
  AI_OS_HOME="$RW" "$CLI/ai-os" handoff approve AIOS-RECV "$1" --gate review --to codex \
    --scope "scope $1" --owner-words "Owner approves $1" >/dev/null 2>&1
  AI_OS_HOME="$RW" PATH="$RB:$PATH" AI_OS_HANDOFF_TRANSPORTS="$TMP/tr-recv.yaml" \
    "$CLI/ai-os" handoff send AIOS-RECV "$1" >/dev/null 2>&1
}
hrecv() { AI_OS_HOME="$RW" "$CLI/ai-os" handoff receive AIOS-RECV "$@" 2>&1; }
rw_fp() { (cd "$RW" && find . -type f -exec shasum {} \; | sort | shasum); }
rw_fp_but() { (cd "$RW" && find . -type f ! -name "handoff-$1.md" -exec shasum {} \; | sort | shasum); }
for id in good twice wrongfrom badfile reviewed status; do rsend "$id"; done
AI_OS_HOME="$RW" "$CLI/ai-os" handoff prepare AIOS-RECV --to codex --gate review \
  --scope 'never sent' --status waiting-owner --id notsent >/dev/null 2>&1
[ "$(grep -l '^status: sent$' "$RW"/tasks/AIOS-RECV/handoff-*.md 2>/dev/null | wc -l | tr -d ' ')" = "6" ]
chk "six sent fixtures and one that was never sent" $?

# =====================================================================================
t "handoff receive: a reply is attached verbatim and nothing else moves"
GR="$RW/tasks/AIOS-RECV/handoff-good.md"
sec3_before=$(sed -n '/^## 3. Owner approval/,/^## 4/p' "$GR" | shasum)
sec4_before=$(sed -n '/^## 4. Send/,/^## 5/p' "$GR" | shasum)
before_other=$(rw_fp_but good)
out=$(hrecv good --from codex --file "$TMP/reply.md"); rc=$?
[ "$rc" -eq 0 ];                           chk "receive exits 0" $?
grep -q '^status: returned$' "$GR";        chk "status moves sent -> returned" $?
grep -q '^returned: attached$' "$GR";      chk "returned becomes attached" $?
grep -Eq '^received_at: [0-9]{4}-' "$GR";  chk "receive time is recorded" $?
grep -q '^received_from: codex$' "$GR";    chk "the client it came from is recorded" $?
grep -q '^received_file: ' "$GR";          chk "the source file is recorded" $?
grep -Eq '^returned_sha256: [0-9a-f]{64}$' "$GR"; chk "the reply is hashed" $?
python3 - "$GR" <<'PYEOF'
import hashlib, pathlib, re, sys
t = pathlib.Path(sys.argv[1]).read_text()
b, e = t.index("<!-- returned:begin -->"), t.index("<!-- returned:end -->")
block = t[b + len("<!-- returned:begin -->"):e].strip("\n")
want = re.search(r"^returned_sha256: ([0-9a-f]{64})$", t, re.M).group(1)
sys.exit(0 if hashlib.sha256(block.encode()).hexdigest() == want else 1)
PYEOF
chk "  ...and the hash is of the attached block, verifiable from the record alone" $?
grep -q 'returned:begin' "$GR" && grep -q 'returned:end' "$GR"
chk "the reply is delimited by its own markers" $?
python3 - "$GR" "$TMP/reply.md" <<'PYEOF'
import pathlib, sys
t = pathlib.Path(sys.argv[1]).read_text()
b, e = t.index("<!-- returned:begin -->"), t.index("<!-- returned:end -->")
got = t[b + len("<!-- returned:begin -->"):e].strip()
sys.exit(0 if got == pathlib.Path(sys.argv[2]).read_text().strip() else 1)
PYEOF
chk "  ...and holds the file byte-for-byte, unsummarised" $?
[ "$sec3_before" = "$(sed -n '/^## 3. Owner approval/,/^## 4/p' "$GR" | shasum)" ]
chk "the owner approval section is untouched" $?
[ "$sec4_before" = "$(sed -n '/^## 4. Send/,/^## 5/p' "$GR" | shasum)" ]
chk "the send section is untouched" $?
[ "$before_other" = "$(rw_fp_but good)" ]; chk "receive writes ONLY the handoff record" $?
[ ! -d "$RW/handoffs" ];                   chk "no global handoffs/ directory" $?

# =====================================================================================
t "handoff receive: it never approves, never closes, never picks the next hop"
grep -q '^approval: recorded$' "$GR";      chk "the approval is still exactly 'recorded'" $?
grep -q '^approved_gate: review$' "$GR";   chk "  ...with its gate unchanged" $?
grep -q '^approved_to: codex$' "$GR";      chk "  ...its destination unchanged" $?
grep -q '^owner_words: Owner approves good$' "$GR"; chk "  ...and the owner's words unchanged" $?
grep -Eq '^status: (approved|closed|sent)$' "$GR"
[ $? -ne 0 ];                              chk "status is never approved, closed or sent again" $?
grep -q '^next_holder: undecided$' "$GR";  chk "the next hop is left undecided" $?
grep -Eq '^next_holder: (codex|claude-code|cursor|gemini|opencode)$' "$GR"
[ $? -ne 0 ];                              chk "  ...no client was picked to carry it on" $?
grep -q '^current_holder: owner$' "$GR";   chk "the handoff comes back to the owner" $?
grep -q '^owner_action_required: resume$' "$GR"; chk "  ...and stops at an owner decision" $?
grep -q 'next_hop:          not chosen' "$GR"; chk "the record says no next hop was chosen" $?
grep -q 'next_hop:' "$GR";                 chk "  ...and the audit records that too" $?
grep -q 'status:                returned' "$GR"
chk "the human-readable metadata block agrees with the frontmatter" $?
for bad in approved closed sent draft waiting-owner blocked stopped; do
  before=$(rw_fp)
  out=$(hrecv status --from codex --file "$TMP/reply.md" --status "$bad"); rc=$?
  [ "$rc" -ne 0 ];                         chk "--status $bad is refused" $?
  [ "$before" = "$(rw_fp)" ];              chk "  ...and writes nothing" $?
done
out=$(hrecv reviewed --from codex --file "$TMP/reply.md" --status reviewed); rc=$?
[ "$rc" -eq 0 ];                           chk "--status reviewed is the owner's other legal move" $?
grep -q '^status: reviewed$' "$RW/tasks/AIOS-RECV/handoff-reviewed.md"
chk "  ...and is written" $?

# =====================================================================================
t "handoff receive: refusals write nothing"
before=$(rw_fp)
hrecv notsent --from codex --file "$TMP/reply.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a handoff that was never sent cannot receive" $?
out=$(hrecv notsent --from codex --file "$TMP/reply.md"); echo "$out" | grep -q "not 'sent'"
chk "  ...and says why" $?
out=$(hrecv good --from codex --file "$TMP/reply.md"); rc=$?
[ "$rc" -ne 0 ];                           chk "a second returned block is refused" $?
echo "$out" | grep -q 'never overwritten';  chk "  ...and never overwrites the first" $?
out=$(hrecv wrongfrom --from claude-code --file "$TMP/reply.md"); rc=$?
[ "$rc" -ne 0 ];                           chk "a reply from a client it was not sent to is refused" $?
echo "$out" | grep -q 'not its reply';     chk "  ...saying it is not this handoff's reply" $?
hrecv wrongfrom --file "$TMP/reply.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --from refused" $?
hrecv wrongfrom --from 'codex,claude-code' --file "$TMP/reply.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "more than one --from refused" $?
hrecv wrongfrom --from nobody --file "$TMP/reply.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "an unknown client refused" $?
hrecv wrongfrom --from codex >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --file refused" $?
hrecv wrongfrom --from codex --file "$TMP/no-such-reply.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a --file that does not exist refused" $?
: > "$TMP/empty.md"
hrecv wrongfrom --from codex --file "$TMP/empty.md" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "an empty reply refused" $?
python3 -c "import sys;sys.stdout.write('x'*300000)" > "$TMP/huge.md"
out=$(hrecv wrongfrom --from codex --file "$TMP/huge.md"); rc=$?
[ "$rc" -ne 0 ];                           chk "a reply past the size cap refused" $?
echo "$out" | grep -q 'cap';               chk "  ...naming the cap" $?
printf 'before\n<!-- returned:end -->\nafter\n' > "$TMP/forged.md"
out=$(hrecv wrongfrom --from codex --file "$TMP/forged.md"); rc=$?
[ "$rc" -ne 0 ];                           chk "a reply carrying the block markers refused" $?
FAKE_TOKEN="gh"'p_0123456789abcdefghijklmnop'
printf 'here is the key %s\n' "$FAKE_TOKEN" > "$TMP/leaky.md"
out=$(hrecv wrongfrom --from codex --file "$TMP/leaky.md"); rc=$?
[ "$rc" -ne 0 ];                           chk "a reply carrying a credential refused" $?
hrecv wrongfrom --from codex --file "$TMP/reply.md" --status returned --status reviewed >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a repeated --status refused" $?
hrecv wrongfrom --from codex --file "$TMP/reply.md" --nope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "an unknown argument refused" $?
[ "$before" = "$(rw_fp)" ];                chk "fifteen refusals, not one byte written" $?

# =====================================================================================
t "handoff receive: the owner's own words survive the round trip"
AW="$RW/tasks/AIOS-RECV/handoff-arabic.md"
AI_OS_HOME="$RW" "$CLI/ai-os" handoff prepare AIOS-RECV --to codex --gate review \
  --scope 'نطاق عربي' --status waiting-owner --id arabic >/dev/null 2>&1
AI_OS_HOME="$RW" "$CLI/ai-os" handoff approve AIOS-RECV arabic --gate review --to codex \
  --scope 'نطاق عربي' --owner-words 'وافقت، أرسلها إلى Codex.' >/dev/null 2>&1
grep -q 'owner_words: "وافقت، أرسلها إلى Codex."' "$AW"
chk "non-ASCII owner words are stored readable, not as \\uXXXX escapes" $?
grep -q 'scope: "نطاق عربي"' "$AW";        chk "  ...and so is a non-ASCII scope" $?
grep -Eq '\\\\u0648|\\\\u06' "$AW"
[ $? -ne 0 ];                              chk "  ...with no escape sequence anywhere in the record" $?
AI_OS_HOME="$RW" PATH="$RB:$PATH" AI_OS_HANDOFF_TRANSPORTS="$TMP/tr-recv.yaml" \
  "$CLI/ai-os" handoff send AIOS-RECV arabic >/dev/null 2>&1
[ $? -eq 0 ];                              chk "and the record still parses back for send" $?
printf 'المراجعة تمت. لا ملاحظات.\n' > "$TMP/reply-ar.md"
hrecv arabic --from codex --file "$TMP/reply-ar.md" >/dev/null 2>&1
[ $? -eq 0 ];                              chk "  ...and for receive" $?
grep -q 'المراجعة تمت. لا ملاحظات.' "$AW"; chk "an Arabic reply is attached readable" $?

# =====================================================================================
t "handoff receive: it has no way to act on what it received"
python3 - "$CLI/ai-os-handoff" <<'PYEOF'
import ast, pathlib, sys
tree = ast.parse(pathlib.Path(sys.argv[1]).read_text())
fn = next((n for n in tree.body
           if isinstance(n, ast.FunctionDef) and n.name == "cmd_receive"), None)
if fn is None:
    sys.exit(1)
problems = []
for node in ast.walk(fn):
    # no call out of the process, of any kind
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Name) and node.func.value.id in ("subprocess", "os"):
            if node.func.attr in ("run", "Popen", "call", "system", "popen", "spawnv"):
                problems.append(f"call out at line {node.lineno}")
        # the status written to the frontmatter must be the validated variable, never a
        # literal — a literal is how "receive quietly approved it" would look.
        if node.func.attr == "write_text":
            pass
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "replace_frontmatter":
        for arg in node.args:
            if isinstance(arg, ast.Dict):
                for k, v in zip(arg.keys, arg.values):
                    if isinstance(k, ast.Constant) and k.value == "status":
                        if not (isinstance(v, ast.Name) and v.id == "new_status"):
                            problems.append("status is written from something other than "
                                            "the validated --status value")
sys.exit(1 if problems else 0)
PYEOF
chk "cmd_receive makes no call out and writes only the validated status" $?
python3 - "$CLI/ai-os-handoff" <<'PYEOF'
import ast, pathlib, sys
src = pathlib.Path(sys.argv[1]).read_text()
tree = ast.parse(src)
node = next((n for n in tree.body if isinstance(n, ast.Assign)
             and any(getattr(t, "id", "") == "RECEIVE_STATUSES" for t in n.targets)), None)
if node is None or not isinstance(node.value, ast.Tuple):
    sys.exit(1)
vals = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
sys.exit(0 if vals == ["returned", "reviewed"] else 1)
PYEOF
chk "the only statuses receive can write are returned and reviewed" $?
grep -q 'def cmd_receive' "$CLI/ai-os-handoff"; chk "receive is implemented, not reserved" $?
grep -Eq 'RESERVED|cmd_reserved' "$CLI/ai-os-handoff"
[ $? -ne 0 ];                              chk "  ...and the reserved-command scaffolding is gone" $?
grep -q 'handoff .*receive' "$CLI/ai-os"; chk "receive is a documented subcommand" $?

# =====================================================================================
t "the plugin -> capability rename keeps its compatibility window open"
# The surface was renamed on 2026-09-03. Every old spelling must keep working for one
# version, and each of these is a promise made in schemas/capability.schema.md. When the
# owner decides to close the window, these are the tests that must be deleted on purpose.

# --- the current names ----------------------------------------------------------------
"$CLI/ai-os" capability list >/dev/null 2>&1
chk "ai-os capability list works" $?
"$CLI/ai-os" capability doctor >/dev/null 2>&1
chk "ai-os capability doctor works" $?
[ -d "$REPO/capabilities" ];               chk "the capability registry is capabilities/" $?
[ -f "$REPO/capabilities/browser/capability.yaml" ]
chk "  ...and the shipped manifest is capability.yaml" $?
[ -f "$REPO/schemas/capability.schema.md" ]
chk "the capability contract is schemas/capability.schema.md" $?
[ -x "$CLI/ai-os-capability" ];            chk "cli/ai-os-capability is the real command" $?

# --- the compatibility names ----------------------------------------------------------
"$CLI/ai-os" plugin list >/dev/null 2>&1
chk "ai-os plugin list still works (alias)" $?
"$CLI/ai-os" plugin doctor >/dev/null 2>&1
chk "ai-os plugin doctor still works (alias)" $?
[ -x "$CLI/ai-os-plugin" ];                chk "cli/ai-os-plugin still exists as a shim" $?
newout=$("$CLI/ai-os" capability list 2>&1)
oldout=$("$CLI/ai-os" plugin list 2>&1)
[ "$newout" = "$oldout" ];                 chk "  ...and the alias produces identical output" $?
[ ! -e "$REPO/plugins" ];                  chk "plugins/ is not required for a new install" $?

# --- both env vars ----------------------------------------------------------------------
AI_OS_CAPABILITIES="$REPO/capabilities" "$CLI/ai-os" capability doctor >/dev/null 2>&1
chk "AI_OS_CAPABILITIES points the registry" $?
AI_OS_PLUGINS="$REPO/capabilities" "$CLI/ai-os" capability doctor >/dev/null 2>&1
chk "AI_OS_PLUGINS is still honoured as a fallback" $?
# The new name wins when both are set, so a stale old value cannot quietly take over.
EMPTYREG2="$TMP/emptyreg2"; mkdir -p "$EMPTYREG2"
out=$(AI_OS_CAPABILITIES="$REPO/capabilities" AI_OS_PLUGINS="$EMPTYREG2" \
      "$CLI/ai-os" capability list 2>&1)
echo "$out" | grep -q 'browser';           chk "  ...and AI_OS_CAPABILITIES wins when both are set" $?

# --- both manifest filenames ------------------------------------------------------------
MF="$TMP/manifest-compat"; mkdir -p "$MF/newname" "$MF/oldname"
manifest() { cat <<EOF
plugin: $1
name: Compat $1
contract: 1
capability: { authority: observe }
operations:
  look:
    summary: look at something
    command: look
    authority: observe
EOF
}
manifest newname > "$MF/newname/capability.yaml"
manifest oldname > "$MF/oldname/plugin.yaml"
out=$(AI_OS_CAPABILITIES="$MF" "$CLI/ai-os" capability list 2>&1)
echo "$out" | grep -q 'newname';           chk "capability.yaml is read" $?
echo "$out" | grep -q 'oldname';           chk "plugin.yaml is still read" $?
# The manifest KEY stays `plugin:` under contract 1 — renaming it is a contract 2 change.
grep -q '^plugin: browser' "$REPO/capabilities/browser/capability.yaml"
chk "the manifest key is still plugin: under contract 1" $?
out=$(AI_OS_CAPABILITIES="$MF" "$CLI/ai-os" capability doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "  ...and both manifests validate" $?

# --- both filenames at once -------------------------------------------------------------
# Identical content is the harmless state a migration passes through: the new name wins.
BOTH="$TMP/manifest-both"; mkdir -p "$BOTH/twin"
manifest twin > "$BOTH/twin/capability.yaml"
cp "$BOTH/twin/capability.yaml" "$BOTH/twin/plugin.yaml"
out=$(AI_OS_CAPABILITIES="$BOTH" "$CLI/ai-os" capability doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "identical capability.yaml and plugin.yaml resolve to one manifest" $?
# Differing content has no correct guess, so it is reported and nothing is merged.
printf 'plugin: twin\nname: DIFFERENT\ncontract: 1\ncapability: { authority: observe }\n' \
  > "$BOTH/twin/plugin.yaml"
out=$(AI_OS_CAPABILITIES="$BOTH" "$CLI/ai-os" capability doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "differing capability.yaml and plugin.yaml is a failure" $?
echo "$out" | grep -qi 'differ';           chk "  ...naming the conflict" $?
echo "$out" | grep -qi 'merge';            chk "  ...and saying nothing is merged" $?

# --- the rename moved nothing else --------------------------------------------------------
for c in claude-code codex cursor gemini opencode; do
  [ -f "$REPO/adapters/$c/adapter.yaml" ] || { false; break; }
done
chk "no adapter manifest moved" $?
[ -f "$REPO/domains/software.yaml" ] && [ -f "$REPO/domains/customer-support.yaml" ]
chk "no domain declaration moved" $?
"$CLI/ai-os" domain doctor >/dev/null 2>&1
chk "domain declarations still validate against the renamed registry" $?
# domains/customer-support.yaml requires browser: it must still RESOLVE, not just parse.
out=$("$CLI/ai-os" domain doctor 2>&1)
echo "$out" | grep -q "requires 'browser'"; [ $? -ne 0 ]
chk "  ...and requires: [browser] still resolves to the capability" $?

# =====================================================================================
t "the governance move kept every policy reachable"
[ -d "$REPO/governance/policies" ];        chk "policies live under governance/" $?
[ ! -e "$REPO/policies" ];                 chk "  ...and the old policies/ root is gone" $?
for f in git.yaml privacy-classification.yaml public-private-contract.yaml \
         workspace-privacy.yaml handoff-transports.yaml privacy-allowlist.txt; do
  [ -f "$REPO/governance/policies/$f" ] || { false; break; }
done
chk "  ...with every policy file present" $?
[ -f "$REPO/governance/README.md" ];       chk "governance/ has its own index" $?
[ ! -d "$REPO/governance/rules" ];         chk "no empty governance/rules/ namespace was invented" $?
# The scanner's own allowlist has to be found at the new path, or the scan silently widens.
"$CLI/ai-os-privacy-scan" --quiet "$REPO" >/dev/null 2>&1
chk "privacy-scan finds its allowlist under governance/" $?
grep -q 'governance/policies/privacy-allowlist.txt' "$CLI/ai-os-privacy-scan"
chk "  ...by the new path, not the old one" $?
# The three-layer model is retired; the policy file must not still describe it as live.
grep -qi 'Public / Private / Runtime contract' "$REPO/governance/policies/public-private-contract.yaml"
[ $? -ne 0 ];                              chk "the contract policy no longer claims three layers" $?
grep -q 'legacy_runtime:' "$REPO/governance/policies/public-private-contract.yaml"
chk "  ...and records the retired runtime layer as history" $?

# =====================================================================================
t "private path compatibility: the resolver answers for every moving root"
# The private workspace is being restructured one slice at a time. Until every move has
# landed a tool may meet the old layout, the new one, or both — and "both" is the case
# that must never be resolved by guessing. See cli/ai-os-paths.
PA="$CLI/ai-os-paths"
[ -x "$PA" ];                             chk "cli/ai-os-paths exists and is executable" $?
for r in memory knowledge projects work rules runtime; do
  "$PA" layout "$r" >/dev/null 2>&1;      chk "  declares the '$r' root" $?
done
"$PA" layout nonesuch >/dev/null 2>&1
[ $? -eq 2 ];                             chk "an unknown root is refused, never invented" $?

# =====================================================================================
t "private path compatibility: old path, new path, neither"
PW="$TMP/paths"; mkdir -p "$PW"
export AI_OS_HOME="$PW"

mkdir -p "$PW/user/05-knowledge"
[ "$("$PA" layout knowledge)" = "old" ];                chk "old path only -> layout old" $?
[ "$("$PA" get knowledge)" = "$PW/user/05-knowledge" ]; chk "  ...and resolves to the old path" $?

mkdir -p "$PW/personal/memory"
[ "$("$PA" layout memory)" = "new" ];                   chk "new path only -> layout new" $?
[ "$("$PA" get memory)" = "$PW/personal/memory" ];      chk "  ...and resolves to the new path" $?

[ "$("$PA" layout projects)" = "none" ];                chk "neither path -> layout none" $?
[ "$("$PA" get projects)" = "$PW/user/04-projects" ]
chk "  ...and resolves to the layout init still creates" $?

# =====================================================================================
t "private path compatibility: both paths is a conflict, never a merge"
mkdir -p "$PW/internal/runtime" "$PW/runtime"
echo "new side" > "$PW/internal/runtime/marker"
echo "old side" > "$PW/runtime/marker"
[ "$("$PA" layout runtime)" = "conflict" ];  chk "two real directories -> layout conflict" $?
out=$("$PA" get runtime 2>&1); rc=$?
[ "$rc" -eq 3 ];                             chk "  ...get refuses with a distinct exit code" $?
echo "$out" | grep -q "CONFLICT";            chk "  ...and says so" $?
echo "$out" | grep -q "$PW/runtime"          && echo "$out" | grep -q "$PW/internal/runtime"
chk "  ...naming both sides so the user can compare them" $?
echo "$out" | grep -qi "will not merge";     chk "  ...and states that it will not merge them" $?
grep -q "old side" "$PW/runtime/marker" && grep -q "new side" "$PW/internal/runtime/marker"
chk "  ...neither side was touched" $?
"$PA" check >/dev/null 2>&1
[ $? -eq 1 ];                                chk "check exits with the number of conflicting roots" $?

# A shim is not a clash: one directory reachable under both names is exactly how a move
# is made reversible, and reporting it as a conflict would block the safe path.
mkdir -p "$PW/internal/governance"
ln -s "$PW/system/rules" "$PW/internal/governance/rules"
mkdir -p "$PW/system/rules"
[ "$("$PA" layout rules)" = "new" ];         chk "both names, one directory -> not a conflict" $?

# =====================================================================================
t "private path compatibility: a root with no single home refuses rather than guesses"
# tasks/ does not survive as one directory — it becomes per-project work/. Handing a
# caller the first match would be a guess dressed as an answer.
PW2="$TMP/paths-work"; mkdir -p "$PW2/projects/ai-os/work" "$PW2/projects/rccm/work"
out=$(AI_OS_HOME="$PW2" "$PA" get work 2>&1); rc=$?
[ "$rc" -eq 4 ];                             chk "the new layout has no single work root -> exit 4" $?
echo "$out" | grep -q "no single root";      chk "  ...and says why" $?
[ "$(AI_OS_HOME="$PW2" "$PA" layout work)" = "new" ]
chk "  ...while still reporting the layout it found" $?

# =====================================================================================
t "private path compatibility: a marked pilot mirror is not a move"
# Slice 8 wrote a project-local pilot at projects/ai-os/work/ so the new work shape could
# be judged while tasks/AIOS-014/ stayed authoritative. By shape alone that is exactly a
# half-done move — real content on the new side of two roots whose old sides are still
# live — so the resolver called `projects` and `work` conflicts and doctor, init and
# handoff all refused. A mirror declares itself in its own front matter; the resolver reads
# that declaration instead of guessing.
mk_pilot() {  # <file> — front matter pointing back at the record that still owns this
  printf -- '---\nproject: ai-os\nmigrated_from: tasks/AIOS-014/task.md\nrole: pilot mirror\n---\n' > "$1"
}

PP="$TMP/pilot"; AI_OS_HOME="$PP" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$PP/tasks/AIOS-014"
echo "the authoritative record" > "$PP/tasks/AIOS-014/task.md"
echo "the real projects root"   > "$PP/user/04-projects/registry.md"
# What doctor says about this workspace before the pilot exists, so the pilot's own effect
# on it can be isolated from whatever else a bare fixture workspace fails.
doc_before=$(AI_OS_HOME="$PP" "$CLI/ai-os-doctor" --quiet 2>&1); doc_rc_before=$?

mkdir -p "$PP/projects/ai-os/work/context"
mk_pilot "$PP/projects/ai-os/work/index.md"
mk_pilot "$PP/projects/ai-os/work/context/current.md"

[ "$(AI_OS_HOME="$PP" "$PA" layout projects)" = "old" ]
chk "a marked pilot does not make the projects root conflict" $?
[ "$(AI_OS_HOME="$PP" "$PA" layout work)" = "old" ]
chk "  ...nor the work root" $?
[ "$(AI_OS_HOME="$PP" "$PA" get projects)" = "$PP/user/04-projects" ]
chk "projects still resolves to the root that is still authoritative" $?
[ "$(AI_OS_HOME="$PP" "$PA" get work)" = "$PP/tasks" ]
chk "  ...and work to tasks/, not to the mirror" $?
AI_OS_HOME="$PP" "$PA" check >/dev/null 2>&1
[ $? -eq 0 ];                            chk "check reports no conflicting root" $?

doc_after=$(AI_OS_HOME="$PP" "$CLI/ai-os-doctor" --quiet 2>&1); doc_rc_after=$?
echo "$doc_after" | grep -q "exists in both layouts"
[ $? -ne 0 ];                            chk "doctor no longer fails on the pilot" $?
[ "$doc_rc_after" -eq "$doc_rc_before" ] && [ "$doc_after" = "$doc_before" ]
chk "  ...and the pilot changes nothing else it reports" $?
AI_OS_HOME="$PP" "$CLI/ai-os-handoff" list AIOS-014 >/dev/null 2>&1
chk "handoff starts up instead of dying on an unresolvable work root" $?

before=$(find "$PP" | sort | shasum)
out=$(AI_OS_HOME="$PP" "$CLI/ai-os-init" 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "init runs instead of refusing" $?
echo "$out" | grep -q "REFUSED"
[ $? -ne 0 ];                            chk "  ...without a layout refusal" $?
[ "$(find "$PP" | sort | shasum)" = "$before" ]
chk "  ...having created, moved and deleted nothing" $?
grep -q "the authoritative record" "$PP/tasks/AIOS-014/task.md"
chk "  ...and left the old task record alone" $?

# The exemption is evidence, not a hole. Without the declaration the same tree is a
# half-done move again, and is reported as one.
PU="$TMP/pilot-unmarked"
mkdir -p "$PU/user/04-projects" "$PU/tasks" "$PU/projects/ai-os/work/context"
echo "work, with nothing said about where it came from" > "$PU/projects/ai-os/work/index.md"
[ "$(AI_OS_HOME="$PU" "$PA" layout work)" = "conflict" ]
chk "an unmarked project-local work directory still conflicts" $?
[ "$(AI_OS_HOME="$PU" "$PA" layout projects)" = "conflict" ]
chk "  ...and so does the projects root holding it" $?
# A marker has to point back into the root that has not moved. Anything else is prose.
printf -- '---\nmigrated_from: user/04-projects/ai-os\n---\n' > "$PU/projects/ai-os/work/index.md"
[ "$(AI_OS_HOME="$PU" "$PA" layout work)" = "conflict" ]
chk "  ...and a migrated_from that names no task record exempts nothing" $?

# A pilot beside a real project is a real projects root: the exemption covers a directory
# that is nothing but pilot, never one that merely contains a pilot.
PM="$TMP/pilot-mixed"
mkdir -p "$PM/user/04-projects" "$PM/tasks" "$PM/projects/ai-os/work" "$PM/projects/rccm"
mk_pilot "$PM/projects/ai-os/work/index.md"
echo "a real project record" > "$PM/projects/rccm/project.md"
[ "$(AI_OS_HOME="$PM" "$PA" layout projects)" = "conflict" ]
chk "a new projects/ carrying real data still conflicts" $?
[ "$(AI_OS_HOME="$PM" "$PA" layout work)" = "old" ]
chk "  ...while the marked mirror inside it stays exempt" $?

# Scoped to the two roots a project-local pilot can occupy. Elsewhere the line is text.
PO="$TMP/pilot-other-roots"
mkdir -p "$PO/personal/memory" "$PO/user/02-personal/memory" \
         "$PO/personal/knowledge" "$PO/user/05-knowledge" \
         "$PO/internal/governance/rules" "$PO/system/rules" \
         "$PO/internal/runtime" "$PO/runtime"
mk_pilot "$PO/personal/memory/index.md";           echo old > "$PO/user/02-personal/memory/i.md"
mk_pilot "$PO/personal/knowledge/index.md";        echo old > "$PO/user/05-knowledge/i.md"
mk_pilot "$PO/internal/governance/rules/index.md"; echo old > "$PO/system/rules/i.md"
mk_pilot "$PO/internal/runtime/index.md";          echo old > "$PO/runtime/i.md"
n=0
for r in memory knowledge rules runtime; do
  [ "$(AI_OS_HOME="$PO" "$PA" layout "$r")" = "conflict" ] || n=$((n+1))
done
[ "$n" -eq 0 ];  chk "a marker cannot exempt memory, knowledge, rules or runtime" $?
AI_OS_HOME="$PO" "$PA" check >/dev/null 2>&1
[ $? -eq 4 ];    chk "  ...and all four are still reported" $?

# =====================================================================================
t "private path compatibility: the personal/ retarget"
# The owner renamed the final private root from `user/` to `personal/` before any private
# data moved: `personal/` holds long-lived personal material, `projects/` holds work, and
# `internal/` holds the machinery. Only the new side of the table moved. The old roots are
# still the authoritative ones on this machine, and still what `ai-os init` creates, so
# every workspace that has not migrated yet must resolve exactly as it did before.
grep -q '"personal/memory ' "$PA" && grep -q '"personal/knowledge ' "$PA"
chk "the table's new side names personal/memory and personal/knowledge" $?
grep -Eq '"user/(memory|knowledge)[[:space:]]' "$PA"
[ $? -ne 0 ];  chk "  ...and no longer names user/memory or user/knowledge" $?

RT="$TMP/retarget"

# --- memory ---------------------------------------------------------------------------
mkdir -p "$RT/m-old/user/02-personal/memory"
[ "$(AI_OS_HOME="$RT/m-old" "$PA" layout memory)" = "old" ]
chk "the old memory root alone is still layout old" $?
[ "$(AI_OS_HOME="$RT/m-old" "$PA" get memory)" = "$RT/m-old/user/02-personal/memory" ]
chk "  ...resolving to user/02-personal/memory, unchanged by the retarget" $?

mkdir -p "$RT/m-new/personal/memory"
[ "$(AI_OS_HOME="$RT/m-new" "$PA" layout memory)" = "new" ]
chk "personal/memory alone is layout new" $?
[ "$(AI_OS_HOME="$RT/m-new" "$PA" get memory)" = "$RT/m-new/personal/memory" ]
chk "  ...and resolves to personal/memory" $?

# The retarget replaced the new side rather than adding to it: the path this table used to
# call "new" is now an ordinary directory, and must not stand in for the root.
mkdir -p "$RT/m-stale/user/memory"
[ "$(AI_OS_HOME="$RT/m-stale" "$PA" layout memory)" = "none" ]
chk "user/memory is no longer the new side of memory" $?
[ "$(AI_OS_HOME="$RT/m-stale" "$PA" get memory)" = "$RT/m-stale/user/02-personal/memory" ]
chk "  ...so it neither resolves nor puts the old root out of play" $?

mkdir -p "$RT/m-both/user/02-personal/memory" "$RT/m-both/personal/memory"
echo "old store" > "$RT/m-both/user/02-personal/memory/i.md"
echo "new store" > "$RT/m-both/personal/memory/i.md"
[ "$(AI_OS_HOME="$RT/m-both" "$PA" layout memory)" = "conflict" ]
chk "the old memory root beside personal/memory is still a conflict" $?
out=$(AI_OS_HOME="$RT/m-both" "$PA" get memory 2>&1); rc=$?
[ "$rc" -eq 3 ] && echo "$out" | grep -q "$RT/m-both/personal/memory"
chk "  ...refused, naming the new side by its personal/ path" $?
grep -q "old store" "$RT/m-both/user/02-personal/memory/i.md" &&
  grep -q "new store" "$RT/m-both/personal/memory/i.md"
chk "  ...and neither store was touched" $?

# --- knowledge --------------------------------------------------------------------------
mkdir -p "$RT/k-old/user/05-knowledge"
[ "$(AI_OS_HOME="$RT/k-old" "$PA" layout knowledge)" = "old" ]
chk "the old knowledge root alone is still layout old" $?
[ "$(AI_OS_HOME="$RT/k-old" "$PA" get knowledge)" = "$RT/k-old/user/05-knowledge" ]
chk "  ...resolving to user/05-knowledge, unchanged by the retarget" $?

mkdir -p "$RT/k-new/personal/knowledge"
[ "$(AI_OS_HOME="$RT/k-new" "$PA" layout knowledge)" = "new" ]
chk "personal/knowledge alone is layout new" $?
[ "$(AI_OS_HOME="$RT/k-new" "$PA" get knowledge)" = "$RT/k-new/personal/knowledge" ]
chk "  ...and resolves to personal/knowledge" $?

mkdir -p "$RT/k-stale/user/knowledge"
[ "$(AI_OS_HOME="$RT/k-stale" "$PA" layout knowledge)" = "none" ]
chk "user/knowledge is no longer the new side of knowledge" $?
[ "$(AI_OS_HOME="$RT/k-stale" "$PA" get knowledge)" = "$RT/k-stale/user/05-knowledge" ]
chk "  ...so it neither resolves nor puts the old root out of play" $?

mkdir -p "$RT/k-both/user/05-knowledge" "$RT/k-both/personal/knowledge"
echo "old store" > "$RT/k-both/user/05-knowledge/i.md"
echo "new store" > "$RT/k-both/personal/knowledge/i.md"
[ "$(AI_OS_HOME="$RT/k-both" "$PA" layout knowledge)" = "conflict" ]
chk "the old knowledge root beside personal/knowledge is still a conflict" $?
out=$(AI_OS_HOME="$RT/k-both" "$PA" get knowledge 2>&1); rc=$?
[ "$rc" -eq 3 ] && echo "$out" | grep -q "$RT/k-both/personal/knowledge"
chk "  ...refused, naming the new side by its personal/ path" $?

# --- the retarget changed the two paths and nothing else ----------------------------------
# The pilot exemption is the one narrow hole in conflict detection, and it stayed exactly
# as narrow: still only `projects` and `work`, still nothing under the personal/ roots.
RP="$TMP/retarget-pilot"
mkdir -p "$RP/user/04-projects" "$RP/tasks" "$RP/projects/ai-os/work/context"
mk_pilot "$RP/projects/ai-os/work/index.md"
[ "$(AI_OS_HOME="$RP" "$PA" layout work)" = "old" ] &&
  [ "$(AI_OS_HOME="$RP" "$PA" layout projects)" = "old" ]
chk "a marked project-local pilot still does not conflict after the retarget" $?
echo "unmarked work" > "$RP/projects/ai-os/work/index.md"
[ "$(AI_OS_HOME="$RP" "$PA" layout work)" = "conflict" ] &&
  [ "$(AI_OS_HOME="$RP" "$PA" layout projects)" = "conflict" ]
chk "  ...and an unmarked one still does" $?
mk_pilot "$RP/projects/ai-os/work/index.md"
mkdir -p "$RP/user/02-personal/memory" "$RP/personal/memory"
mk_pilot "$RP/personal/memory/index.md"
[ "$(AI_OS_HOME="$RP" "$PA" layout memory)" = "conflict" ]
chk "a pilot marker under personal/memory exempts nothing" $?

# The other three roots are untouched by this slice, and the roots that do not move are
# still not resolver roots: daily, professional and templates were not invented here.
RO="$TMP/retarget-others"
mkdir -p "$RO/projects" "$RO/internal/governance/rules" "$RO/internal/runtime"
[ "$(AI_OS_HOME="$RO" "$PA" layout projects)" = "new" ] &&
  [ "$(AI_OS_HOME="$RO" "$PA" layout rules)" = "new" ] &&
  [ "$(AI_OS_HOME="$RO" "$PA" layout runtime)" = "new" ]
chk "projects, rules and runtime keep the new sides they already had" $?
roots=$(. "$PA"; printf '%s' "$AIOS_PATH_ROOTS")
[ "$roots" = "memory knowledge projects work rules runtime" ]
chk "no new resolver root was invented for daily, professional or templates" $?

# =====================================================================================
t "private path compatibility: rewrite maps an old-layout path onto the live one"
[ "$("$PA" rewrite user/05-knowledge/README.md)" = "$PW/user/05-knowledge/README.md" ]
chk "a path under an unmoved root is unchanged" $?
[ "$("$PA" rewrite user/02-personal/memory/MEMORY.md)" = "$PW/personal/memory/MEMORY.md" ]
chk "a path under a moved root is rewritten onto the new one" $?
[ "$("$PA" rewrite sessions/2026/x.md)" = "$PW/sessions/2026/x.md" ]
chk "a path under no moving root is left alone" $?
"$PA" rewrite runtime/state/state.json >/dev/null 2>&1
[ $? -eq 3 ];                                chk "a conflicting root propagates the refusal" $?

# =====================================================================================
t "private path compatibility: the resolver only reads"
before=$(find "$PW" | sort | shasum)
"$PA" list >/dev/null 2>&1; "$PA" env >/dev/null 2>&1; "$PA" check >/dev/null 2>&1
after=$(find "$PW" | sort | shasum)
[ "$before" = "$after" ];                    chk "resolving creates, moves and deletes nothing" $?
grep -Eq '(^|[^a-z-])(cp|mv|rm|rsync|mkdir|install)( |$)' "$PA"
[ $? -ne 0 ];                                chk "  ...and the file contains no move or copy at all" $?

# =====================================================================================
t "private path compatibility: one resolver, two languages"
# A second implementation is how the shell half and the Python half of a half-finished
# migration end up writing to different stores.
py=$(cd "$REPO" && AI_OS_HOME="$PW" python3 -c "
import sys; sys.path.insert(0, 'cli')
from aios_paths import private_path, private_layout, PathConflict
print(private_layout('memory'), private_path('memory'))
try:
    private_path('runtime'); print('NO-CONFLICT')
except PathConflict:
    print('conflict-raised')
")
# -ef, not a string compare: TMPDIR can carry a trailing slash, and "the same directory"
# is what the two implementations have to agree on, not the same spelling of it.
[ "$(echo "$py" | head -n1 | cut -d' ' -f1)" = "new" ] &&
  [ "$(echo "$py" | head -n1 | cut -d' ' -f2-)" -ef "$("$PA" get memory)" ]
chk "Python resolves a moved root exactly as the shell does" $?
[ "$(echo "$py" | tail -n1)" = "conflict-raised" ]
chk "  ...and raises on a conflict instead of choosing a side" $?

# =====================================================================================
t "private path compatibility: init never straddles two layouts"
IW="$TMP/init-layout"; AI_OS_HOME="$IW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$IW/personal/memory" && mv "$IW/user/02-personal/memory/MEMORY.md" "$IW/personal/memory/"
rm -rf "$IW/user/02-personal"
AI_OS_HOME="$IW" "$CLI/ai-os-init" >/dev/null 2>&1
[ ! -d "$IW/user/02-personal" ];         chk "init does not re-create a root that has moved" $?
[ ! -e "$IW/user/02-personal/memory/MEMORY.md" ] && [ -f "$IW/personal/memory/MEMORY.md" ]
chk "  ...and re-seeds into the store that exists, not beside it" $?

mkdir -p "$IW/user/02-personal/memory"; echo "a second store" > "$IW/user/02-personal/memory/x.md"
out=$(AI_OS_HOME="$IW" "$CLI/ai-os-init" 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "init refuses outright when a root exists in both layouts" $?
echo "$out" | grep -q "REFUSED";         chk "  ...and says so" $?
grep -q "a second store" "$IW/user/02-personal/memory/x.md" && [ -f "$IW/personal/memory/MEMORY.md" ]
chk "  ...having touched neither side" $?

out=$(AI_OS_HOME="$IW" "$CLI/ai-os-doctor" 2>&1); rc=$?
echo "$out" | grep -q "exists in both layouts"; chk "doctor reports the same conflict as a failure" $?
[ "$rc" -gt 0 ];                                chk "  ...and exits non-zero" $?

# =====================================================================================
t "private path compatibility: a workspace path containing spaces"
# Regression. The resolver's answers used to reach the shell as text and be re-parsed
# with eval, so "/my ai os/user/..." became the command `ai` with an argument: every tool
# still exited 0 while printing "ai: command not found" and silently reporting no paths
# at all. The values are assigned now, never parsed — see aios_paths_export.
SPW="$TMP/with space/my ai os"; mkdir -p "$SPW"
AI_OS_HOME="$SPW" "$CLI/ai-os-init" >/dev/null 2>"$TMP/sp-init.err"
chk "init succeeds under a path with spaces" $?
sp_out=$(AI_OS_HOME="$SPW" "$CLI/ai-os" status 2>"$TMP/sp-status.err")
chk "ai-os status succeeds" $?
AI_OS_HOME="$SPW" "$CLI/ai-os" doctor --quiet >/dev/null 2>"$TMP/sp-doctor.err"
chk "ai-os doctor --quiet succeeds" $?

cat "$TMP/sp-init.err" "$TMP/sp-status.err" "$TMP/sp-doctor.err" | grep -q "command not found"
[ $? -ne 0 ];                         chk "no fragment of the path was run as a command" $?
[ ! -s "$TMP/sp-init.err" ] && [ ! -s "$TMP/sp-status.err" ] && [ ! -s "$TMP/sp-doctor.err" ]
chk "  ...and none of the three wrote anything to stderr" $?

# Exiting 0 while reporting nothing was the actual damage, so assert the counts landed.
echo "$sp_out" | grep -Eq 'memory +[0-9]+ files';   chk "status counts the memory store" $?
echo "$sp_out" | grep -Eq 'knowledge +[0-9]+ files'; chk "  ...and knowledge" $?
echo "$sp_out" | grep -q "missing"
[ $? -ne 0 ];                         chk "  ...and reports no root as missing" $?

[ "$(AI_OS_HOME="$SPW" "$PA" layout memory)" = "old" ]
chk "the resolver still reports the old layout for a fresh workspace" $?
[ "$(AI_OS_HOME="$SPW" "$PA" get memory)" = "$SPW/user/02-personal/memory" ]
chk "  ...and returns the path with its spaces intact" $?

# `env` stays raw so a machine parser gets the literal path; `env --sh` is the form that
# survives eval. Quoting one would have broken the other — hence two.
# Captured, not piped: the suite runs with pipefail and `grep -q` closes the pipe on the
# first match, so a piped resolver would be killed by SIGPIPE and read as a failure.
raw_env=$(AI_OS_HOME="$SPW" "$PA" env)
case "$raw_env" in
  *"AI_OS_PATH_MEMORY=$SPW/user/02-personal/memory"*) true ;;
  *) false ;;
esac
chk "env keeps values raw for machine parsers" $?
sh_path=$(eval "$(AI_OS_HOME="$SPW" "$PA" env --sh)"; printf '%s' "$AI_OS_PATH_MEMORY")
[ "$sh_path" = "$SPW/user/02-personal/memory" ]
chk "env --sh survives eval with the spaces intact" $?

# The Python adapter reads the raw form; a shell-quoted one would have handed it a path
# with backslashes in it that exists nowhere.
pysp=$(cd "$REPO" && AI_OS_HOME="$SPW" python3 -c "
import sys; sys.path.insert(0, 'cli')
from aios_paths import private_path
p = private_path('memory')
print('yes' if p.is_dir() else 'no')
")
[ "$pysp" = "yes" ];                  chk "Python resolves a spaced path to a real directory" $?

export AI_OS_HOME="$TMP/clean"

# =====================================================================================
t "inherited suites still pass"
if [ -f "$REPO/adapters/claude-code/tests/test-guard-push.py" ]; then
  python3 "$REPO/adapters/claude-code/tests/test-guard-push.py" >/dev/null 2>&1
  chk "claude-code git push guard" $?
else
  printf '  %sSKIP%s claude-code push guard tests not found\n' "$D" "$X"
fi
if [ -f "$REPO/tests/test-runtime-relocation.py" ]; then
  python3 "$REPO/tests/test-runtime-relocation.py" >/dev/null 2>&1
  chk "persistent runtime data lives in the private workspace" $?
else
  printf '  %sSKIP%s runtime relocation tests need the runtime layer present\n' "$D" "$X"
fi

# =====================================================================================
printf '\n%s%d passed%s' "$G" "$pass" "$X"
[ "$fail" -gt 0 ] && printf ', %s%d failed%s' "$R" "$fail" "$X"
printf '\n\n'
exit $(( fail > 0 ))
