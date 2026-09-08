#!/usr/bin/env bash
# tests/test-contract.sh — the V0.1.3 Public/Private Contract, exercised for real.
#
# Every test runs against a throwaway workspace in a temp dir. Nothing here touches the
# real ~/atlas, ~/.ai, or the user's Claude settings — the point of a contract test is
# to prove the boundary holds, not to cross it.
set -uo pipefail

# T-033: the developer shell now exports ATLAS_REPO (and may export ATLAS_REPO) for
# real use. Fixture-isolation tests below set these per-invocation to prove specific
# resolution paths — an ambient value would silently win before the test's own override
# is even reached, so both must start unset here regardless of the calling shell.
unset ATLAS_REPO ATLAS_REPO

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$REPO/cli"; export CLI
TMP="$(mktemp -d "${TMPDIR:-/tmp}/atlas-test.XXXXXX")"
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
export ATLAS_CLAUDE_PROJECTS="$TMP/claude-projects"
export ATLAS_CLAUDE_SETTINGS="$TMP/claude-settings.json"
mkdir -p "$ATLAS_CLAUDE_PROJECTS"
echo '{}' > "$ATLAS_CLAUDE_SETTINGS"

# =====================================================================================
t "init on a clean workspace"
W="$TMP/clean"; export ATLAS_HOME="$W"
out=$("$CLI/atlas-init" 2>&1); rc=$?
chk "exits 0" $rc
for s in internal/config internal/governance/rules internal/governance/policies \
         internal/schemas internal/extensions/skills internal/extensions/agents \
         internal/helpers internal/runtime personal/inbox personal/daily \
         personal/memory personal/professional personal/knowledge personal/templates \
         projects internal/sessions; do
  [ -d "$W/$s" ]; chk "created $s/" $?
done
[ -d "$W/personal/memory/education" ];  chk "created the 8 memory sections" $?
[ -d "$W/personal/knowledge/decisions" ];        chk "created the 7 knowledge kinds" $?
[ -f "$W/personal/memory/MEMORY.md" ];  chk "seeded memory/MEMORY.md" $?
[ ! -d "$W/internal/config/scripts" ];     chk "did NOT seed runtime scripts into private data" $?
[ ! -d "$W/internal/extensions/skills/research" ];           chk "did NOT copy public skills into the workspace" $?
[ ! -d "$W/.git" ];                      chk "did NOT create a git repo (never a remote)" $?

# =====================================================================================
t "init is idempotent — second and third run change nothing"
before=$(find "$W" -type f -exec shasum {} \; | sort | shasum)
"$CLI/atlas-init" >/dev/null 2>&1
"$CLI/atlas-init" >/dev/null 2>&1
after=$(find "$W" -type f -exec shasum {} \; | sort | shasum)
[ "$before" = "$after" ];                chk "three runs, byte-identical workspace" $?

# =====================================================================================
t "init never overwrites user-owned content"
echo "MY OWN NOTES — do not touch" > "$W/personal/memory/MEMORY.md"
echo "a real memory" > "$W/personal/memory/education/scholarship.md"
mkdir -p "$W/internal/extensions/skills/research"; echo "my own research skill" > "$W/internal/extensions/skills/research/SKILL.md"
out=$("$CLI/atlas-init" 2>&1)
grep -q "MY OWN NOTES" "$W/personal/memory/MEMORY.md";        chk "edited seed file preserved verbatim" $?
grep -q "a real memory" "$W/personal/memory/education/scholarship.md"; chk "user memory file untouched" $?
grep -q "my own research skill" "$W/internal/extensions/skills/research/SKILL.md"; chk "user skill NOT overwritten by the public one" $?
grep -q "yours" <<< "$out";                       chk "reports the divergence instead of resolving it" $?

# =====================================================================================
t "init --dry-run writes nothing"
D2="$TMP/dryrun"; export ATLAS_HOME="$D2"
"$CLI/atlas-init" --dry-run >/dev/null 2>&1
[ ! -d "$D2" ];                          chk "dry run created no directory at all" $?

# =====================================================================================
t "init refuses a wrong root"
ATLAS_HOME="$REPO" "$CLI/atlas-init" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "refuses to initialize into the public repo" $?
ATLAS_HOME="$HOME/.ai" "$CLI/atlas-init" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "refuses to initialize into the runtime" $?

# =====================================================================================
t "doctor: clean workspace passes"
export ATLAS_HOME="$TMP/clean"
# The legacy layer is NOT created here. Until V0.1.5, ~/.ai was the runtime layer and
# this fixture seeded it with bin/{ai-memory,ai-guard-push,ai-sync} because doctor
# checked those were present. V0.1.5 retired ~/.ai and inverted the check: an active
# component left in the legacy layer is now a FAILURE — a second source of truth. The
# fixture was never updated, so it was manufacturing the very violation it then asserted
# was absent. Nothing reads those binaries any more; the two tests below still need
# $ATLAS_RUNTIME to be *settable*, not populated.
export ATLAS_RUNTIME="$TMP/fake-runtime"
out=$("$CLI/atlas-doctor" 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "no failures on a freshly initialized workspace" $?

# =====================================================================================
# Removing that fixture must not be able to hide a regression in the check it was
# tripping, so assert the check still fires — from both directions.
t "doctor: an active component in the legacy layer is still a failure"
LEG="$TMP/legacy-live"; mkdir -p "$LEG/bin"
out=$(ATLAS_RUNTIME="$LEG" "$CLI/atlas-doctor" 2>&1); rc=$?
echo "$out" | grep -q "legacy layer still holds active Atlas components"
chk "bin/ left in the legacy layer is reported" $?
echo "$out" | grep -q "second source of truth"
chk "  ...with the reason, not just the fact" $?
[ "$rc" -gt 0 ];                         chk "  ...and doctor exits non-zero" $?
rm -rf "$LEG"
out=$("$CLI/atlas-doctor" 2>&1); rc=$?
echo "$out" | grep -q "no legacy layer on this machine"
chk "an absent legacy layer is clean, not missing" $?
[ "$rc" -eq 0 ];                         chk "  ...and doctor stays at zero problems" $?

# =====================================================================================
t "doctor: detects wrong roots"
out=$(ATLAS_RUNTIME="$ATLAS_HOME" "$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "same directory";  chk "runtime == private detected" $?
NEST="$TMP/clean/nested-public"; mkdir -p "$NEST"
out=$(cd "$NEST" && ATLAS_HOME="$TMP/clean" "$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -qi "nested";         chk "public repo nested inside private detected" $?

# =====================================================================================
t "doctor: detects a nested repository"
mkdir -p "$ATLAS_HOME/some-project/.git"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "nested git repository inside the private workspace"; chk "nested .git found and reported" $?
rm -rf "$ATLAS_HOME/some-project"

# =====================================================================================
t "doctor: detects a remote on the private workspace"
git -C "$ATLAS_HOME" init -q 2>/dev/null
git -C "$ATLAS_HOME" remote add origin https://example.com/leak.git
out=$("$CLI/atlas-doctor" 2>&1); rc=$?
echo "$out" | grep -q "PRIVATE workspace has a git remote"; chk "remote detected" $?
[ "$rc" -gt 0 ];                         chk "exits non-zero" $?
[ -n "$(git -C "$ATLAS_HOME" remote -v)" ]; chk "did NOT remove the remote (diagnostic, not destructive)" $?
rm -rf "$ATLAS_HOME/.git"

# =====================================================================================
t "doctor: memory symlink validation"
P="$ATLAS_CLAUDE_PROJECTS"
mkdir -p "$P/good" && ln -s "$ATLAS_HOME/personal/memory" "$P/good/memory"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "1 client memory link(s), all ->"; chk "a correct link is reported as correct" $?
echo "$out" | grep -q "recursive memory link";           rc=$?; [ $rc -ne 0 ]; chk "a correct link is NOT called recursive" $?

mkdir -p "$P/broken" && ln -s "$TMP/does-not-exist" "$P/broken/memory"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "broken memory link";            chk "broken link detected" $?
rm -rf "$P/broken"

mkdir -p "$P/outside" "$TMP/rogue-memory" && ln -s "$TMP/rogue-memory" "$P/outside/memory"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "OUTSIDE the private workspace"; chk "target outside the workspace detected" $?
echo "$out" | grep -q "different stores";              chk "conflicting stores detected" $?
rm -rf "$P/outside"

mkdir -p "$P/real/memory"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "real directory, not a link";    chk "duplicate live store (real dir) detected" $?
rm -rf "$P/real"

STALE="$ATLAS_RUNTIME/workspace/memory"; mkdir -p "$STALE"
mkdir -p "$P/stale" && ln -s "$STALE" "$P/stale/memory"
out=$("$CLI/atlas-doctor" 2>&1)
echo "$out" | grep -q "FROZEN pre-cutover archive";    chk "link to the frozen archive detected" $?
rm -rf "$P/stale" "$ATLAS_RUNTIME/workspace"
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
out=$("$CLI/atlas-privacy-scan" "$F" 2>&1); rc=$?
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
out=$(ATLAS_HOME="$TMP/clean" "$CLI/atlas-privacy-scan" "$F" 2>&1)
echo "$out" | grep -q "PERSONAL.*user term"; [ $? -ne 0 ]
chk "unknown term not flagged without a terms file" $?
mkdir -p "$TMP/clean/internal/governance/policies"; echo "$TERM" > "$TMP/clean/internal/governance/policies/privacy-terms.txt"
out=$(ATLAS_HOME="$TMP/clean" "$CLI/atlas-privacy-scan" "$F" 2>&1)
echo "$out" | grep -q "PERSONAL.*user term";         chk "term from ~/atlas is applied" $?
grep -rqi "$TERM" "$REPO" --exclude-dir=.git; [ $? -ne 0 ]
chk "the term itself never entered the public repo" $?
rm -f "$TMP/clean/internal/governance/policies/privacy-terms.txt"

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
out=$("$CLI/atlas-privacy-scan" "$GI" 2>&1); rc=$?
echo "$out" | grep -q "tracked-copy.txt"
chk "a home path in a NON-ignored file is still reported" $?
echo "$out" | grep -q "derived/.root"; [ $? -ne 0 ]
chk "  ...while the same path in an ignored file is exempt" $?
rm -f "$GI/tracked-copy.txt"

out=$("$CLI/atlas-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "a repo whose only findings are ignored scans clean" $?
echo "$out" | grep -q "git-ignored";                 chk "  ...and says so in the header, never silently" $?

# --include-ignored must restore the strict behaviour, or the exemption is unauditable.
out=$("$CLI/atlas-privacy-scan" --include-ignored "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "--include-ignored reports it again" $?
echo "$out" | grep -q "derived/.root";               chk "  ...naming the ignored file" $?

# THE LINE THAT MUST NOT MOVE: an ignored file is a common home for a real secret.
AWSKEY2="AKIA""IOSFODNN7EXAMPLE"
printf 'aws_key = %s\n' "$AWSKEY2" > "$GI/derived/leak.txt"
out=$("$CLI/atlas-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "a CREDENTIAL in an ignored file still fails the scan" $?
echo "$out" | grep -q "AWS access key id";           chk "  ...and is named" $?
echo "$out" | grep -q "1 credential";                chk "  ...classified as credential, not personal" $?
rm -f "$GI/derived/leak.txt"

# The exemption is git's answer, not a hardcoded directory name.
printf '' > "$GI/.gitignore"
out=$("$CLI/atlas-privacy-scan" "$GI" 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "un-ignoring the file brings the finding back" $?

t "privacy scan: licence attribution is allowed only in a licence context"
LC="$TMP/licence"; mkdir -p "$LC"
# A generated term, for the same reason as every other user-term test here: a real name
# written into this file would put it in the public repo.
LTERM="zz$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')corp"
LHOME="$TMP/lhome"; mkdir -p "$LHOME/internal/governance/policies"
echo "$LTERM" > "$LHOME/internal/governance/policies/privacy-terms.txt"
# NB: capture, never `lscan | grep`. The scanner exits 1 when it finds something and the
# suite runs under `set -o pipefail`, so a pipe reports the scanner's exit, not grep's.
lscan() { ATLAS_HOME="$LHOME" "$CLI/atlas-privacy-scan" "$LC" 2>&1; }

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
grep -q 'COPYRIGHT_LINE = re.compile' "$CLI/atlas-privacy-scan"
chk "licence attribution is a pattern in the scanner, not a literal name" $?
n=$(grep -cvE '^[[:space:]]*(#|$)' "$REPO/governance/policies/privacy-allowlist.txt")
[ "$n" -eq 14 ]
chk "the allowlist gained no entry — every one is a hole in the scan ($n)" $?
grep -q "^exceptions:" "$REPO/governance/policies/privacy-classification.yaml"
chk "both exemptions are documented as policy" $?
# And the scan of this very repository is the real guard: if a name, a home path or an
# email ever lands in a tracked file, the cleanliness test below fails. That is what
# caught this test's own first draft.

t "privacy scan: no false positive on the repository's own text"
out=$("$CLI/atlas-privacy-scan" "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "the public repo scans clean" $?

# =====================================================================================
t "public repository cleanliness (working tree AND full history)"
out=$("$CLI/atlas-privacy-scan" --history --quiet "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no personal data anywhere in git history" $?

# =====================================================================================
t "adapter contract: the real registry"
out=$("$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "all shipped manifests valid" $?
n=$(echo "$out" | grep -c '^  ok ')
[ "$n" -eq 9 ];                                      chk "9 manifests present and parsed" $?
echo "$out" | grep -q "consumer not verified";       chk "unverified consumers are flagged, not hidden" $?
"$CLI/atlas-adapter" list 2>&1 | grep -q "cursor.*nothing"
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
  rules: { path: $ATLAS_HOME/user/02-personal/memory/stolen.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
echo "$out" | grep -q "INSIDE \$ATLAS_HOME";          chk "provides: path inside \$ATLAS_HOME is rejected" $?
[ "$rc" -gt 0 ];                                     chk "  ...and it is a hard failure" $?
rm -rf "$F2/badpath"

# AIOS-016: the same hard rule must hold under $ATLAS_HOME, the current canonical root —
# $ATLAS_HOME is a legacy compatibility alias (README.md), not the only private workspace.
mk badatlas <<EOF
adapter: badatlas
name: Bad Atlas
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: $TMP/a16-atlas-check/user/stolen.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(ATLAS_HOME="$TMP/a16-atlas-check" ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
echo "$out" | grep -q "INSIDE \$ATLAS_HOME";          chk "provides: path inside \$ATLAS_HOME is ALSO rejected" $?
[ "$rc" -gt 0 ];                                     chk "  ...and it is a hard failure" $?
rm -rf "$F2/badatlas"

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
out=$(ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1)
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
out=$(ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1)
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
out=$(ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1)
echo "$out" | grep -q "unknown core resource";         chk "an undeclared core resource is rejected" $?
rm -rf "$F2/greedy"

# malformed: reports, exits non-zero, changes nothing
mkdir -p "$F2/broken"; printf 'adapter: broken\n\tbad: [unclosed\n' > "$F2/broken/adapter.yaml"
before=$(shasum "$F2/broken/adapter.yaml")
out=$(ATLAS_ADAPTERS="$F2" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "a malformed manifest fails" $?
[ "$before" = "$(shasum "$F2/broken/adapter.yaml")" ]; chk "  ...and nothing was modified" $?
rm -rf "$F2/broken"

# =====================================================================================
t "adapter contract: AIOS-016 \`adapter init\` — detection"
# Every invocation below pins its own ATLAS_HOME/ATLAS_ADAPTERS to a throwaway path under
# $TMP so nothing here ever reads or writes the real ~/atlas or the real adapters/ tree.
A16_EMPTY="$TMP/a16-empty-adapters"; mkdir -p "$A16_EMPTY"
A16_HOME="$TMP/a16-home"

out=$(ATLAS_ACTIVE_ADAPTER=ignored ATLAS_HOME="$A16_HOME" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init scratchtool --skip 2>&1)
echo "$out" | grep -q "scratchtool (explicit)"
chk "explicit id on the command line wins over \$ATLAS_ACTIVE_ADAPTER" $?

out=$(ATLAS_ACTIVE_ADAPTER=scratchtool ATLAS_HOME="$A16_HOME" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init --skip 2>&1)
echo "$out" | grep -q "scratchtool (detected)"
chk "\$ATLAS_ACTIVE_ADAPTER is read when no explicit id, confidence=detected" $?

out=$(ATLAS_ACTIVE_ADAPTER= ATLAS_HOME="$A16_HOME" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init 2>&1); rc=$?
echo "$out" | grep -q "unknown"
chk "no id and no env var -> unknown, refuses rather than guessing" $?
[ "$rc" -eq 2 ];                                     chk "  ...exit code 2" $?
[ ! -d "$A16_HOME" ];                                chk "  ...detection alone never writes anything" $?

out=$(ATLAS_HOME="$A16_HOME" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init '../../evil' --approve 2>&1); rc=$?
echo "$out" | grep -q "invalid tool id"
chk "a path-traversal / garbage tool id is refused, not sanitized-and-used" $?
[ "$rc" -eq 2 ];                                     chk "  ...exit code 2" $?
[ ! -d "$A16_HOME" ];                                chk "  ...and nothing escaped the draft root" $?

out=$(ATLAS_HOME="$A16_HOME" "$CLI/atlas-adapter" init claude-code 2>&1); rc=$?
echo "$out" | grep -q "official adapter present"
chk "a real, already-official adapter (claude-code) validates clean, no draft" $?
[ "$rc" -eq 0 ];                                     chk "  ...exit 0" $?
[ ! -d "$A16_HOME/runtime/draft-adapters/claude-code" ]
chk "  ...no draft dir was created for an official adapter" $?

t "adapter contract: AIOS-016 \`adapter init\` — draft scaffold lifecycle"
A16_HOME2="$TMP/a16-home2"
adapters_before=$(find "$REPO/adapters" -type f -exec shasum {} \; | sort | shasum)

out=$(ATLAS_HOME="$A16_HOME2" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init scratchtool --skip 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "skip exits 0" $?
[ ! -d "$A16_HOME2/runtime/draft-adapters/scratchtool" ]
chk "  ...and creates nothing" $?

out=$(ATLAS_HOME="$A16_HOME2" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init scratchtool 2>&1); rc=$?
echo "$out" | grep -q "Approve"
chk "missing required input (no --approve/--skip) prints the owner prompt" $?
[ "$rc" -eq 3 ];                                     chk "  ...refuses (non-zero exit), no silent action" $?
[ ! -d "$A16_HOME2/runtime/draft-adapters/scratchtool" ]
chk "  ...and still nothing was written" $?

out=$(ATLAS_HOME="$A16_HOME2" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init scratchtool --approve 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "approve exits 0" $?
A16_DD="$A16_HOME2/runtime/draft-adapters/scratchtool"
[ -f "$A16_DD/adapter.yaml" ] && [ -f "$A16_DD/integration.md" ] && [ -f "$A16_DD/metadata.json" ]
chk "approve creates exactly the 3 draft files" $?
A16_M="$A16_DD/adapter.yaml"
grep -q '^adapter: scratchtool$' "$A16_M"
chk "  manifest: adapter: equals the directory name" $?
grep -q '^status: draft$' "$A16_M";                  chk "  manifest: status: draft" $?
grep -q '^contract: 1$' "$A16_M";                    chk "  manifest: contract: 1" $?
grep -q '^client:$' "$A16_M" && grep -q 'consumer_verified: false' "$A16_M"
chk "  manifest: client block present, consumer_verified false (never true on a draft)" $?
grep -q '^provides: {}$' "$A16_M" && grep -q '^requires: \[\]$' "$A16_M" \
  && grep -q '^enforces: \[\]$' "$A16_M"
chk "  manifest: provides/requires/enforces empty (the AI must not invent capabilities)" $?
grep -q '^draft:$' "$A16_M" && grep -q 'promotion_state: awaiting-review' "$A16_M"
chk "  manifest: draft block present with promotion_state" $?

before=$(find "$A16_HOME2" -type f -exec shasum {} \; | sort | shasum)
out=$(ATLAS_HOME="$A16_HOME2" ATLAS_ADAPTERS="$A16_EMPTY" \
      "$CLI/atlas-adapter" init scratchtool 2>&1); rc=$?
after=$(find "$A16_HOME2" -type f -exec shasum {} \; | sort | shasum)
[ "$rc" -eq 0 ];                                     chk "re-running on an existing draft exits 0" $?
echo "$out" | grep -q "draft already exists"
chk "  ...and reports the draft already exists" $?
[ "$before" = "$after" ];                            chk "  ...byte-identical, no new files (idempotent)" $?

adapters_after=$(find "$REPO/adapters" -type f -exec shasum {} \; | sort | shasum)
[ "$adapters_before" = "$adapters_after" ]
chk "no write ever landed in the real adapters/ tree" $?

# Simulate promotion (an owner hand-commit): the same id now resolves as an OFFICIAL
# adapter. Re-running must validate that one and leave the stale draft alone — never
# resurrect or recreate it.
A16_PROMOTED="$TMP/a16-promoted-adapters"; mkdir -p "$A16_PROMOTED/scratchtool"
cat > "$A16_PROMOTED/scratchtool/adapter.yaml" <<'EOF'
adapter: scratchtool
name: Scratchtool
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides: {}
requires: []
writes: []
EOF
draft_before=$(shasum "$A16_M")
out=$(ATLAS_HOME="$A16_HOME2" ATLAS_ADAPTERS="$A16_PROMOTED" \
      "$CLI/atlas-adapter" init scratchtool 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "re-running after promotion exits 0" $?
echo "$out" | grep -q "official adapter present"
chk "  ...validates the OFFICIAL adapter, not the draft" $?
draft_after=$(shasum "$A16_M")
[ "$draft_before" = "$draft_after" ]
chk "  ...the stale draft is left untouched, not resurrected" $?

top=$(find "$A16_HOME2" -mindepth 1 -maxdepth 1 -type d -exec basename {} \; | sort | tr '\n' ' ')
[ "$top" = "runtime " ]
chk "only runtime/ exists under \$ATLAS_HOME — no config/policy path was ever written" $?

rm -rf "$A16_EMPTY" "$A16_HOME" "$A16_HOME2" "$A16_PROMOTED"

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
}
# gemini's manifest declares writes: [] (consumer_verified: false — path confirmed,
# consumption not observed), so load_registry() correctly places it in project_only
# alongside cursor/opencode rather than in the writable table above. The mission-pilot
# adapters (claude-code-mission-pilot, claude-code-tools-pilot, gemini-cli-mission-pilot)
# and the disposable atlas-fixture registry fixture are unverified/writes-nothing too.
EXPECTED_PROJECT_ONLY = ["atlas-fixture", "claude-code-mission-pilot",
                         "claude-code-tools-pilot", "cursor", "gemini",
                         "gemini-cli-mission-pilot", "opencode"]
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
# in cli/atlas-adapter and is borrowed by cli/atlas-capability, so ONE parser serves both
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
# through ATLAS_PLUGINS below is also the compatibility-window proof.
for src in "$REPO"/capabilities/*/capability.yaml; do
  cid=$(basename "$(dirname "$src")"); mkdir -p "$FMT/plugins/$cid"
  reflow "$src" "$FMT/plugins/$cid/plugin.yaml"
done
n=$(grep -c '^[[:space:]]*[{[]' "$FMT"/adapters/*/adapter.yaml | awk -F: '{s+=$2} END {print s+0}')
[ "$n" -gt 0 ];                                      chk "the adapter fixture really is reflowed ($n wrapped collections)" $?

out=$(ATLAS_ADAPTERS="$FMT/adapters" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "reflowed adapter manifests still validate" $?
[ "$(echo "$out" | grep -c '^  ok ')" -eq 9 ];       chk "  ...all 9, none unreadable" $?
echo "$out" | grep -qi "flow collection"; [ $? -ne 0 ]
chk "  ...and no flow-collection complaint" $?

# The two layouts must not merely both parse — they must parse to the SAME document.
# (drop the header line, which echoes the fixture directory and so always differs)
inline=$(ATLAS_ADAPTERS="$REPO/adapters" "$CLI/atlas-adapter" list 2>&1 | grep -v 'adapters  ')
split=$(ATLAS_ADAPTERS="$FMT/adapters" "$CLI/atlas-adapter" list 2>&1 | grep -v 'adapters  ')
[ "$inline" = "$split" ];                            chk "inline and split forms parse identically" $?

# The capability registry borrows this parser, so the same reflow must be safe there too.
out=$(ATLAS_PLUGINS="$FMT/plugins" "$CLI/atlas-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "reflowed capability manifests still validate" $?
inline=$(ATLAS_PLUGINS="$REPO/capabilities" "$CLI/atlas-capability" list 2>&1 | grep -v 'capabilities  ')
split=$(ATLAS_PLUGINS="$FMT/plugins" "$CLI/atlas-capability" list 2>&1 | grep -v 'capabilities  ')
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
out=$(ATLAS_PLUGINS="$F4" "$CLI/atlas-capability" doctor 2>&1); rc=$?
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
out=$(ATLAS_ADAPTERS="$F3" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
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
out=$(ATLAS_ADAPTERS="$F3" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
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
out=$(ATLAS_ADAPTERS="$F3" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "content after a wrapped collection still fails" $?
echo "$out" | grep -qi "content after the flow collection"
chk "  ...naming the trailing content" $?
rm -rf "$F3" "$F4"

t "the formatter that broke the registry is fenced off"
[ -f "$REPO/.prettierignore" ];                      chk ".prettierignore ships with the repo" $?
grep -q '^adapters/' "$REPO/.prettierignore";        chk "  ...covering adapters/" $?
grep -q '^capabilities/' "$REPO/.prettierignore";     chk "  ...covering capabilities/" $?
grep -q '^governance/' "$REPO/.prettierignore";      chk "  ...covering governance/" $?
grep -q '^contracts/' "$REPO/.prettierignore";         chk "  ...covering the yaml fences in contracts/" $?
[ -f "$REPO/.vscode/settings.json" ];                chk "repo-level editor settings disable format-on-save" $?
grep -q '"editor.formatOnSave": false' "$REPO/.vscode/settings.json"
chk "  ...for anyone who clones it, not just this machine" $?

t "adapter enable/disable refuse until wired (no dead state)"
out=$("$CLI/atlas-adapter" enable claude-code 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "enable refuses" $?
echo "$out" | grep -q "Step 8";                      chk "  ...and names the step that would wire it" $?
[ ! -e "$ATLAS_HOME/internal/config/plugins.yaml" ]; chk "  ...and wrote no registry state" $?

# =====================================================================================
t "profile: the public template carries no values"
TPL="$REPO/templates/workspace/internal/config/profile.yaml"
[ -f "$TPL" ];                                       chk "profile.yaml template exists" $?
grep -qE '^(vcs_owner|  default|  summary|  tool|  curator): *""$' "$TPL"
chk "template ships blank values, not someone's" $?
grep -q 'never leaves ~/atlas' "$TPL";              chk "template states it is private" $?

t "profile: init seeds it once and never overwrites"
P3="$TMP/profilews"; export ATLAS_HOME="$P3"
"$CLI/atlas-init" >/dev/null 2>&1
[ -f "$P3/internal/config/profile.yaml" ];             chk "init seeds internal/config/profile.yaml" $?
echo "vcs_owner: my-own-handle" > "$P3/internal/config/profile.yaml"
out=$("$CLI/atlas-init" 2>&1)
grep -q "my-own-handle" "$P3/internal/config/profile.yaml";   chk "an edited profile is never overwritten" $?
grep -q "yours.*profile.yaml" <<< "$out";         chk "  ...and the divergence is reported" $?

t "render: unresolved placeholders are visible, never silently blank"
printf 'x {{profile.nothing.here}} y\n' > "$TMP/probe.md"
mkdir -p "$REPO/skills/__probe__" && cp "$TMP/probe.md" "$REPO/skills/__probe__/SKILL.md"
out=$(ATLAS_HOME="$P3" "$CLI/atlas-render" __probe__ 2>&1)
echo "$out" | grep -q '\[\[profile.nothing.here unset\]\]'
chk "an unset value renders as an explicit marker" $?
echo "$out" | grep -qE '^x  y$'; [ $? -ne 0 ];       chk "  ...not as an empty string" $?
rm -rf "$REPO/skills/__probe__"

t "render: client conventions come from the adapter manifest"
export ATLAS_HOME="$HOME/atlas"
a=$("$CLI/atlas-render" catch-up --client claude-code 2>&1 | grep -c 'CLAUDE.md')
b=$("$CLI/atlas-render" catch-up --client codex 2>&1 | grep -c 'AGENTS.md')
[ "$a" -gt 0 ];                                      chk "claude-code resolves to CLAUDE.md" $?
[ "$b" -gt 0 ];                                      chk "codex resolves to AGENTS.md" $?
c=$("$CLI/atlas-render" catch-up --client codex 2>&1 | grep -c 'CLAUDE.md')
[ "$c" -eq 0 ];                                      chk "  ...and codex gets no Claude filename" $?

t "THE SKILL GATE: 9 skills render equivalent to the committed goldens"
# This gate began as a migration check: the canonical bodies had to render equivalent to
# the hand-maintained copy in the runtime layer. That copy was rendered with the real
# user's profile — it carried their org folders and VCS handle — so it could never live
# here, and it retires with ~/.ai. The proof is preserved by rendering against a fictional
# fixture profile and diffing the committed goldens instead: same skill set, same
# renderer, same client conventions, no private data and no runtime dependency.
# Skill count here tracks <atlas repo>/skills/*; bump it and regenerate the goldens
# (atlas-render <skill> --client claude-code > tests/fixtures/golden-skills/<skill>/SKILL.md)
# whenever a skill is added, removed, or its canonical body changes (T-023 added
# session-handoff and edited catch-up/session-end — 8 -> 9; T-115 removed graphify — 9 -> 8).
GW="$TMP/goldenws"; mkdir -p "$GW/internal/config"
cp "$REPO/tests/fixtures/profile.yaml" "$GW/internal/config/profile.yaml"
out=$(ATLAS_HOME="$GW" "$CLI/atlas-render" --check "$REPO/tests/fixtures/golden-skills" \
        --client claude-code 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no semantic loss across all 8 skills" $?
# Count per-skill result lines only — the summary line says "equivalent" too.
n=$(echo "$out" | grep -cE '^  (identical|equivalent) ')
[ "$n" -eq 8 ];                                      chk "all 8 accounted for ($n)" $?
echo "$out" | grep -q "DIFFERS"; [ $? -ne 0 ];       chk "no skill differs semantically" $?
# The goldens are public artefacts and must stay that way.
ATLAS_HOME="$GW" "$CLI/atlas-privacy-scan" "$REPO/tests/fixtures" >/dev/null 2>&1
chk "the goldens carry no private data" $?
# Independence, proved by construction rather than by grepping this file: run the same
# gate with a HOME that has no runtime layer under it at all. If it still passes, nothing
# in the path from canonical body to golden touches ~/.ai.
NOAI="$TMP/no-runtime-home"; mkdir -p "$NOAI"
HOME="$NOAI" ATLAS_HOME="$GW" "$CLI/atlas-render" --check \
  "$REPO/tests/fixtures/golden-skills" --client claude-code >/dev/null 2>&1
chk "the gate passes with no runtime layer present" $?

t "public skills carry no personal values"
# The terms are read from the PRIVATE term file, never spelled out here: a test that
# names the strings it asserts are absent puts them in the repo it is guarding.
TERMS="${ATLAS_HOME:-$HOME/atlas}/internal/governance/policies/privacy-terms.txt"
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
hits=$(grep -Eic 'claude|codex|gemini|cursor|opencode' "$CLI/atlas-memory" || true)
[ "$hits" -eq 0 ];   chk "0 client references in cli/atlas-memory" $?
grep -q 'if client' "$CLI/atlas-memory"
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
ATLAS_HOME="$MW" "$CLI/atlas-init" >/dev/null 2>&1
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
export ATLAS_ADAPTERS="$MP"

out=$(ATLAS_HOME="$MW" "$CLI/atlas-memory" attach 2>&1); rc=$?
[ "$rc" -eq 0 ];                                 chk "core attaches a non-Claude client's mounts" $?
[ -L "$TMP/tc-home/proj-a/memory" ];             chk "mount a is now a symlink" $?
# Compared by inode: the target string may differ harmlessly from $MW (a trailing slash
# in TMPDIR, a symlinked /tmp) while pointing at exactly the same store.
[ -L "$TMP/tc-home/proj-b/memory" ] && [ "$TMP/tc-home/proj-b/memory" -ef "$MW/personal/memory" ]
chk "mount b resolves to the canonical store" $?
out=$(ATLAS_HOME="$MW" "$CLI/atlas-memory" status 2>&1)
echo "$out" | grep -q 'linked'                   ; chk "status reports it linked" $?
ATLAS_HOME="$MW" "$CLI/atlas-memory" doctor >/dev/null 2>&1
chk "doctor passes on a freshly attached non-Claude workspace" $?
env | grep -qi 'claude' && claude_in_env=1 || claude_in_env=0
[ "$claude_in_env" -eq 0 ] || [ -z "${ATLAS_ADAPTERS##*mem-adapters}" ]
chk "the engine resolved no Claude adapter at all" $?

t "memory engine: attach --here asks the adapter which mount serves this directory"
# Step 10 needs exact parity with the historical `link`: one directory, not all of them.
mkdir -p "$TMP/tc-home/proj-here"
out=$(cd "$TMP/tc-home/proj-here" && ATLAS_HOME="$MW" "$CLI/atlas-memory" attach --here 2>&1)
[ -L "$TMP/tc-home/proj-here/memory" ];          chk "--here attached the current directory" $?
[ ! -e "$TMP/tc-home/proj-d/memory" ];           chk "   ...and only that one" $?
out=$(ATLAS_HOME="$MW" "$CLI/atlas-memory" attach --here /some/path 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "--here with a PATH is refused" $?
out=$(ATLAS_HOME="$MW" "$CLI/atlas-memory" attach --bogus 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "an unknown option is refused, not ignored" $?
grep -q 'cwd' "$CLI/atlas-memory";               chk "core resolves cwd through the adapter, not a rule of its own" $?

t "memory engine: attach never destroys user data"
mkdir -p "$TMP/tc-home/proj-c/memory"
echo 'irreplaceable' > "$TMP/tc-home/proj-c/memory/keep.md"
QT="$TMP/quarantine"
ATLAS_HOME="$MW" ATLAS_MEMORY_QUARANTINE="$QT" \
  "$CLI/atlas-memory" attach "$TMP/tc-home/proj-c/memory" >/dev/null 2>&1
[ -L "$TMP/tc-home/proj-c/memory" ];             chk "the path became a link" $?
found=$(grep -rl 'irreplaceable' "$QT" 2>/dev/null | wc -l)
[ "$found" -eq 1 ];                              chk "the pre-existing file was rescued, not deleted" $?

t "memory engine: an unverified integration is never called"
sed 's/verified: true }/verified: false }/' "$MP/testclient/adapter.yaml" > "$TMP/pv" \
  && mv "$TMP/pv" "$MP/testclient/adapter.yaml"
rm -f "$TMP/tc-home/proj-a/memory" "$TMP/tc-home/proj-b/memory"
out=$(ATLAS_HOME="$MW" "$CLI/atlas-memory" attach 2>&1)
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
out=$(ATLAS_ADAPTERS="$TMP/bad-adapters" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "an unknown integration point fails" $?
echo "$out" | grep -q 'may not invent one';      chk "   ...with a reason, not a guess" $?

mkdir -p "$TMP/bad-adapters2/badcmd"
sed 's|memory.everything: { command: x,|memory.mounts: { command: ../../etc/x,|' \
  "$TMP/bad-adapters/badint/adapter.yaml" | sed 's/adapter: badint/adapter: badcmd/' \
  > "$TMP/bad-adapters2/badcmd/adapter.yaml"
out=$(ATLAS_ADAPTERS="$TMP/bad-adapters2" "$CLI/atlas-adapter" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "a command escaping its adapter dir fails" $?
unset ATLAS_ADAPTERS

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
HK="$CLI/atlas-hook"

mk_repo() {  # $1 = repo dir. A minimal stand-in: one repo-relative executable.
  mkdir -p "$1/cli"
  printf '#!/bin/sh\necho "RESOLVED:$(cd "$(dirname "$0")/.." && pwd)"\n' > "$1/cli/probe"
  chmod +x "$1/cli/probe"
}
mk_ws() {    # $1 = workspace dir, $2 = atlas_repo value (may be empty or ~-relative)
  mkdir -p "$1/internal/config"; printf 'atlas_repo: %s\n' "$2" > "$1/internal/config/settings.yaml"
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
R1="$FH/atlas"; mk_repo "$R1"; mk_ws "$TMP/ws1" "$R1"
out=$(ATLAS_HOME="$TMP/ws1" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "repository directly under \$HOME" $?

# 2. under Documents
R2="$FH/Documents/atlas"; mk_repo "$R2"; mk_ws "$TMP/ws2" "$R2"
out=$(ATLAS_HOME="$TMP/ws2" "$HK" cli/probe 2>&1)
resolves "$R2" "$out";                          chk "repository under Documents/" $?

# 3. nested five deep, and 4. an arbitrary directory name
R3="$FH/a/b/c/d/e/my-weird-atlas-checkout"; mk_repo "$R3"; mk_ws "$TMP/ws3" "$R3"
out=$(ATLAS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R3" "$out";                          chk "repository nested 5+ deep" $?
echo "$out" | grep -q 'my-weird-atlas-checkout'
chk "repository directory name is arbitrary" $?

# 5. a ~-prefixed value, expanded against HOME
R5="$FH/tilde-repo"; mk_repo "$R5"; mk_ws "$TMP/ws5" '~/tilde-repo'
out=$(HOME="$FH" ATLAS_HOME="$TMP/ws5" "$HK" cli/probe 2>&1)
resolves "$R5" "$out";                          chk "a ~-prefixed atlas_repo expands" $?

# 7. explicit override wins over the configured value
out=$(ATLAS_REPO="$R1" ATLAS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "ATLAS_REPO overrides the configured value" $?

# 8. ATLAS_REPO (canonical, T-032) also overrides the configured value
out=$(ATLAS_REPO="$R1" ATLAS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "ATLAS_REPO overrides the configured value" $?

# 9. A retired variable cannot override the canonical engine location.
out=$(env "AI""_OS_REPO=$FH/decoy-repo" ATLAS_REPO="$R1" ATLAS_HOME="$TMP/ws3" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "ATLAS_REPO ignores a retired environment override" $?

t "hook launcher: a broken installation fails loudly, never silently"
# 6. empty value
mk_ws "$TMP/ws6" ""
out=$(ATLAS_HOME="$TMP/ws6" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "empty atlas_repo exits non-zero" $?
echo "$out" | grep -q "atlas init";             chk "   ...and says how to fix it" $?
out=$(ATLAS_HOME="$TMP/nonexistent-ws" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a missing workspace config exits non-zero" $?
mk_ws "$TMP/ws8" "$TMP/no-such-repo"
out=$(ATLAS_HOME="$TMP/ws8" "$HK" cli/probe 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a recorded path that does not exist exits non-zero" $?
out=$(ATLAS_HOME="$TMP/ws1" "$HK" cli/not-there 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "a missing repo-relative command exits non-zero" $?

t "hook launcher: no client knowledge, and none of this machine"
n=$(grep -Eic 'claude|codex|gemini|cursor|opencode' "$HK" || true)
[ "$n" -eq 0 ];                                 chk "the launcher names no client" $?
n=$(grep -Eic 'Documents|Projects|Developer|/Users/' "$HK" || true)
[ "$n" -eq 0 ];                                 chk "the launcher hardcodes no location" $?

t "hook launcher: works under a hook's minimal environment"
# 8. exactly what a client hook gets: no inherited env, a bare PATH.
out=$(env -i HOME="$FH" PATH=/usr/bin:/bin ATLAS_HOME="$TMP/ws1" "$HK" cli/probe 2>&1)
resolves "$R1" "$out";                          chk "resolves under env -i with a minimal PATH" $?

t "hook launcher: moving the repository does not touch any hook"
# 10. THE INVARIANT. The invocation string below is written once and never changed;
# only the recorded location moves.
INVOCATION="cli/probe"
MV_FROM="$TMP/relocate/first/place/atlas"; MV_TO="$TMP/relocate/somewhere/entirely/different/renamed-os"
mk_repo "$MV_FROM"; mk_ws "$TMP/ws-mv" "$MV_FROM"
out=$(ATLAS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1)
resolves "$MV_FROM" "$out";                     chk "resolves at its original location" $?
mkdir -p "$(dirname "$MV_TO")" && mv "$MV_FROM" "$MV_TO"
out=$(ATLAS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1); rc=$?
[ "$rc" -ne 0 ];                                chk "after the move, the stale location fails loudly" $?
mk_ws "$TMP/ws-mv" "$MV_TO"                     # the one thing that changes: the record
out=$(ATLAS_HOME="$TMP/ws-mv" "$HK" $INVOCATION 2>&1)
resolves "$MV_TO" "$out";                       chk "the SAME invocation works after relocation" $?

t "init records the repository location, and never overwrites yours"
# 11. empty -> recorded automatically
IW="$TMP/init-ws"
ATLAS_HOME="$IW" "$CLI/atlas-init" >/dev/null 2>&1
got=$(sed -n 's/^atlas_repo:[[:space:]]*//p' "$IW/internal/config/settings.yaml" | head -1)
[ "$got" = "$REPO" ];                           chk "init recorded its own actual location" $?
# 12. explicit value survives
sed 's|^atlas_repo:.*|atlas_repo: ~/deliberately/elsewhere|' "$IW/internal/config/settings.yaml" > "$TMP/x" \
  && mv "$TMP/x" "$IW/internal/config/settings.yaml"
out=$(ATLAS_HOME="$IW" "$CLI/atlas-init" 2>&1)
got=$(sed -n 's/^atlas_repo:[[:space:]]*//p' "$IW/internal/config/settings.yaml" | head -1)
[ "$got" = "~/deliberately/elsewhere" ];        chk "an explicit atlas_repo is NOT overwritten" $?
grep -q "kept your value" <<< "$out";        chk "   ...and the divergence is reported" $?
# dry run must still write nothing
rm -rf "$TMP/init-dry"
ATLAS_HOME="$TMP/init-dry" "$CLI/atlas-init" --dry-run >/dev/null 2>&1
[ ! -e "$TMP/init-dry" ];                       chk "--dry-run records nothing" $?

t "the installed hook commands carry no machine-specific path"
# 9. The user's real settings.json, if the launcher is installed.
SJ="$HOME/.claude/settings.json"
if [ -f "$SJ" ] && grep -q 'atlas-hook' "$SJ"; then
  n=$(grep -Eoc '"command": "[^"]*(Documents|Projects|Developer)/' "$SJ" || true)
  [ "$n" -eq 0 ];                               chk "no repository path in any hook command" $?
  grep -q '\$HOME/.claude/atlas-hook cli/atlas memory attach --here' "$SJ"
  chk "SessionStart goes through the launcher" $?
  grep -q '\$HOME/.claude/atlas-hook adapters/claude-code/ai-guard-push' "$SJ"
  chk "PreToolUse goes through the launcher" $?
  cmp -s "$HOME/.claude/atlas-hook" "$CLI/atlas-hook"
  chk "the installed launcher matches the repository's copy" $?
  [ ! -L "$HOME/.claude/atlas-hook" ];          chk "it is a copy, not a symlink" $?
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
n=$(grep -c 'search(r"\^atlas_repo' "$SY" || true)
[ "$n" -eq 0 ];                                      chk "   ...and never resolved from atlas_repo:" $?

t "ai-sync honours ATLAS_HOME for runtime state (T-020: runtime/caches/backups moved off the ATLAS_HOME-compat resolver; RULES/PROFILE stay on it, untouched)"
grep -q 'ATLAS_HOME = Path(os.environ.get("ATLAS_HOME"' "$SY"
chk "ATLAS_HOME is still read, for RULES/PROFILE" $?
# Runtime/caches/backups are Atlas-canonical as of T-020 — resolved from ATLAS_HOME
# directly, not through the ATLAS_HOME-compat private_path_or_die() resolver that
# RULES/PROFILE still use above.
grep -q 'ATLAS_HOME = Path(os.environ\["ATLAS_HOME"\]) if os.environ.get("ATLAS_HOME")' "$SY"
chk "ATLAS_HOME is read from the environment for runtime state" $?
grep -q 'RUNTIME = ATLAS_HOME / "runtime"' "$SY";    chk "   ...runtime resolves under it" $?
grep -q 'CACHES = RUNTIME / "caches"' "$SY";         chk "   ...caches" $?
grep -q 'STATE = CACHES / "state" / "state.json"' "$SY"; chk "   ...state" $?
grep -q 'BACKUPS = RUNTIME / "backups"' "$SY";       chk "   ...backups" $?

t "the retired ~/.ai layer is completely removed"
# ~/.ai kept the engine, then a shim, then a frozen archive — and is now deleted
# entirely (user decision, 2026-08-31). Nothing may recreate it.
[ ! -e "$HOME/.ai" ];                                chk "~/.ai no longer exists at all" $?

t "SessionEnd runs the engine through the dynamic launcher"
SJ="$HOME/.claude/settings.json"
if [ -f "$SJ" ] && grep -q 'atlas-hook' "$SJ"; then
  grep -q '\$HOME/.claude/atlas-hook cli/ai-sync sync' "$SJ"
  chk "SessionEnd goes through the launcher" $?
  grep -q '\$HOME/.ai/bin/ai-sync' "$SJ"
  [ $? -ne 0 ];                                      chk "   ...and no longer through ~/.ai/bin" $?
  n=$(grep -Ec '"command": "[^"]*(Documents|Projects|Developer)/' "$SJ" || true)
  [ "$n" -eq 0 ];                                    chk "no hook embeds a repository path" $?
  env -i HOME="$HOME" PATH=/usr/bin:/bin sh -c \
    '$HOME/.claude/atlas-hook cli/ai-sync verify' >/dev/null 2>&1
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
OB="$TMP/onboard"; export ATLAS_HOME="$OB"
"$CLI/atlas-init" >/dev/null 2>&1
[ -f "$OB/internal/config/workspace.yaml" ];        chk "init seeds the workspace state file" $?
grep -q '^status: uninitialized' "$OB/internal/config/workspace.yaml"; chk "seeded as uninitialized" $?
"$CLI/atlas-onboard" status >/dev/null 2>&1
[ $? -eq 10 ];                                    chk "status exits 10 = onboarding required" $?
# The point of a canonical marker: a workspace full of directories is still uninitialized.
[ -d "$OB/personal/memory" ] && "$CLI/atlas-onboard" status >/dev/null 2>&1; [ $? -eq 10 ]
chk "directories existing does NOT count as initialized" $?

# =====================================================================================
t "onboarding: completion is earned, not announced"
"$CLI/atlas-onboard" complete >/dev/null 2>&1
[ $? -ne 0 ];                                     chk "complete refuses with no data collected" $?
grep -q '^status: uninitialized' "$OB/internal/config/workspace.yaml"; chk "  ...and did not mark initialized" $?

# =====================================================================================
t "onboarding: an interrupted run resumes where it stopped"
"$CLI/atlas-onboard" set name "Test User" >/dev/null 2>&1
chk "first answer accepted" $?
"$CLI/atlas-onboard" status >/dev/null 2>&1
[ $? -eq 11 ];                                    chk "status exits 11 = incomplete, resumable" $?
grep -q '^step_identity: done' "$OB/internal/config/workspace.yaml";    chk "answered step recorded done" $?
grep -q '^step_language: pending' "$OB/internal/config/workspace.yaml"; chk "unanswered step still pending" $?
"$CLI/atlas-onboard" set language "English" >/dev/null 2>&1
"$CLI/atlas-onboard" complete >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "resumed run completes" $?
"$CLI/atlas-onboard" status >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "status exits 0 = initialized" $?

# =====================================================================================
t "onboarding: idempotent — repeat runs change nothing and duplicate nothing"
ob_before=$(find "$OB" -type f -exec shasum {} \; | sort | shasum)
ob_when=$(grep '^initialized_at:' "$OB/internal/config/workspace.yaml")
"$CLI/atlas-onboard"          >/dev/null 2>&1
"$CLI/atlas-onboard" complete >/dev/null 2>&1
"$CLI/atlas-onboard" --adopt  >/dev/null 2>&1
"$CLI/atlas-init"             >/dev/null 2>&1
ob_after=$(find "$OB" -type f -exec shasum {} \; | sort | shasum)
[ "$ob_before" = "$ob_after" ];                   chk "four further runs, byte-identical workspace" $?
[ "$ob_when" = "$(grep '^initialized_at:' "$OB/internal/config/workspace.yaml")" ]
chk "the initialization timestamp is written once, never moved" $?
[ "$(grep -c '^status:' "$OB/internal/config/workspace.yaml")" -eq 1 ]; chk "no duplicated state key" $?
[ "$(find "$OB/personal/memory/identity" -name '*.md' | wc -l | tr -d ' ')" -eq 1 ]
chk "no duplicated identity record" $?

# =====================================================================================
t "onboarding: never re-interviews or overwrites a completed workspace"
"$CLI/atlas-onboard" set name "SOMEONE ELSE" >/dev/null 2>&1
[ $? -eq 3 ];                                     chk "refuses to re-answer on an initialized workspace" $?
grep -q "Test User" "$OB/personal/memory/identity/profile.md"; chk "the original name survives" $?
grep -q "SOMEONE ELSE" "$OB/personal/memory/identity/profile.md"
[ $? -ne 0 ];                                     chk "the new name was never written" $?
out=$("$CLI/atlas-onboard" 2>&1)
echo "$out" | grep -q "already initialized";      chk "a bare run says so instead of asking again" $?

# =====================================================================================
t "onboarding: an existing workspace is adopted, not re-created"
AD="$TMP/adopt"; export ATLAS_HOME="$AD"
"$CLI/atlas-init" >/dev/null 2>&1
"$CLI/atlas-onboard" --adopt >/dev/null 2>&1
[ $? -ne 0 ];                                     chk "refuses to adopt a workspace with no data" $?
echo "# MY OWN PROFILE"     > "$AD/personal/memory/identity/profile.md"
echo "# MY OWN PREFERENCES" > "$AD/personal/memory/preferences/working-style.md"
mem_before=$(find "$AD/personal/memory" -type f -exec shasum {} \; | sort | shasum)
"$CLI/atlas-onboard" --adopt >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "adopts a workspace whose data already exists" $?
mem_after=$(find "$AD/personal/memory" -type f -exec shasum {} \; | sort | shasum)
[ "$mem_before" = "$mem_after" ];                 chk "adoption wrote no memory file at all" $?
grep -q "MY OWN PROFILE" "$AD/personal/memory/identity/profile.md"
chk "pre-existing user data preserved byte-for-byte" $?

# =====================================================================================
t "onboarding: a marker that outruns the data is reported, not believed"
rm -f "$AD/personal/memory/identity/profile.md"
"$CLI/atlas-onboard" status >/dev/null 2>&1
[ $? -eq 12 ];                                    chk "status exits 12 = inconsistent" $?
out=$("$CLI/atlas-onboard" status 2>&1)
echo "$out" | grep -q "INCONSISTENT";             chk "names the inconsistency instead of passing" $?
echo "$out" | grep -q -- "--repair";              chk "offers a deterministic recovery path" $?
was=$(grep '^initialized_at:' "$AD/internal/config/workspace.yaml")
"$CLI/atlas-onboard" --repair >/dev/null 2>&1
grep -q '^step_identity: pending' "$AD/internal/config/workspace.yaml"; chk "repair reopens the missing step" $?
grep -q '^step_language: done'    "$AD/internal/config/workspace.yaml"; chk "  ...and only the missing step" $?
[ -f "$AD/personal/memory/preferences/working-style.md" ]
chk "repair destroyed no surviving data" $?
[ "$was" = "$(grep '^initialized_at:' "$AD/internal/config/workspace.yaml")" ]
chk "repair preserved the original initialization date" $?

# =====================================================================================
t "onboarding is client-agnostic"
grep -Eqi 'claude|codex|gemini|cursor|opencode' "$CLI/atlas-onboard"
[ $? -ne 0 ];                                     chk "no client is named anywhere in the source" $?
grep -Eq '\.claude|\.codex|\.gemini|\.cursor|opencode' "$CLI/atlas-onboard"
[ $? -ne 0 ];                                     chk "no client-owned path is read or written" $?
# It must complete on a machine where no client is installed at all.
NC="$TMP/noclient"; export ATLAS_HOME="$NC"
"$CLI/atlas-init" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/atlas-onboard" set name "N" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/atlas-onboard" set language "N" >/dev/null 2>&1
HOME="$TMP/empty-home" "$CLI/atlas-onboard" complete >/dev/null 2>&1
[ $? -eq 0 ];                                     chk "completes with no AI client present" $?
"$CLI/atlas-onboard" detect | grep -q '^clients:'; chk "detection reports clients from the registry" $?

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
[ -f "$REPO/contracts/adapter.schema.md" ]; chk "adapter contract has its own schema" $?
[ -f "$REPO/contracts/capability.schema.md" ];  chk "capability contract has its own schema" $?
grep -q 'adapter.*connects.*one AI client' "$REPO/contracts/adapter.schema.md"
chk "the adapter schema describes clients" $?
grep -qi 'capability' "$REPO/contracts/capability.schema.md"
chk "the plugin schema describes capabilities" $?

# =====================================================================================
t "namespace: the two registries are distinct commands over distinct roots"
"$CLI/atlas-adapter" list 2>&1 | grep -q 'claude-code'
chk "atlas adapter lists client adapters" $?
"$CLI/atlas-adapter" list 2>&1 | grep -q "adapters"
chk "  ...from the adapters root" $?
# Superseded by AIOS-007: plugins/ is no longer empty — the browser capability ships.
"$CLI/atlas-capability" list 2>&1 | grep -q 'browser'
chk "atlas capability lists the shipped capabilities" $?
"$CLI/atlas-capability" doctor >/dev/null 2>&1
chk "the capability registry validates" $?
# An EMPTY registry must still be valid, not an error — the property the old test held.
EMPTYREG="$TMP/empty-registry"; mkdir -p "$EMPTYREG"
ATLAS_PLUGINS="$EMPTYREG" "$CLI/atlas-capability" list 2>&1 | grep -q 'no capabilities'
chk "an empty registry still reports itself as empty" $?
ATLAS_PLUGINS="$EMPTYREG" "$CLI/atlas-capability" doctor >/dev/null 2>&1
chk "  ...and is valid, not an error" $?
# The client registry must never answer capability questions, or the split is cosmetic.
"$CLI/atlas-capability" list 2>&1 | grep -q 'claude-code'
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
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "a well-formed capability validates" $?
echo "$out" | grep -q 'demo: manifest valid'; chk "  ...and is reported valid" $?
ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" list 2>&1 | grep -q 'demo'
chk "capability discovery finds it" $?
ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" list 2>&1 | grep -q 'build'
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
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
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
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1)
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
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'must be a bare filename'
chk "a command that escapes its own directory is rejected" $?

cap <<'EOF'
plugin: x
name: From The Future
contract: 2
capability: { domain: d, authority: observe }
EOF
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'DISABLED'
chk "contract 2 on a contract-1 core is disabled with a reason" $?

cap <<'EOF'
plugin: x
name: No Authority
contract: 1
capability: { domain: d }
EOF
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'authority is required'
chk "an unstated authority rung is refused, not defaulted" $?

cap <<'EOF'
plugin: notx
name: Mismatched
contract: 1
capability: { domain: d, authority: observe }
EOF
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1)
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
out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "a satisfied dependency validates" $?
echo "$out" | grep -q 'WARN'
[ $? -ne 0 ];                             chk "  ...with no warning" $?
ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" list 2>&1 | grep -q 'beta'
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
out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
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
  out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
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
out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'not a valid capability id';  chk "a malformed id is rejected" $?

dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: [alpha]
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'is itself';        chk "a self-dependency is rejected" $?

dep <<'EOF'
plugin: alpha
name: Alpha
contract: 1
capability: { domain: demo, authority: propose }
requires: beta
operations: { go: { summary: s, command: c, verify: v } }
EOF
out=$(ATLAS_PLUGINS="$DF" "$CLI/atlas-capability" doctor 2>&1)
echo "$out" | grep -q 'must be a list';   chk "a non-list requires: is rejected" $?

# No resolver was built, and none should appear by accident.
grep -qi 'transitive\|topological\|resolve_deps' "$CLI/atlas-capability"
[ $? -ne 0 ];                             chk "no dependency resolver was introduced" $?

# =====================================================================================
t "core stays domain-agnostic"
# The architectural test: Core must never branch on what a domain means. Asserted against
# both registries — the capability one, and the domain one that now owns the concept.
grep -Eq 'domain *== *"(software|sales|marketing|design|research|finance)"' "$CLI/atlas-capability"
[ $? -ne 0 ];                             chk "the capability registry has no domain branching" $?
grep -Eq '(domain|outcome) *== *"' "$CLI/atlas-domain"
[ $? -ne 0 ];                             chk "the domain registry branches on no id or outcome name" $?
# The falsifier for the whole design: adding a second domain must not have required
# touching CLI logic. Expressed as an absence — Core names none of what ships in domains/.
grep -Eqi '\b(software|customer-support|mobile-app|resolved-ticket|web-application)\b' "$CLI/atlas-domain"
[ $? -ne 0 ];                             chk "Core names no shipped domain or outcome — the second domain needed no CLI change" $?

# The capability contract no longer carries a `domain:` field at all. It was removed rather
# than renamed when Domain became a real concept: core never read it, nothing validated it,
# and one manifest set it — so one word now has exactly one meaning.
grep -Eq '^\s*domain:' "$REPO/capabilities/browser/capability.yaml"
[ $? -ne 0 ];                             chk "the browser capability declares no domain field" $?
grep -Eq '^\s+domain: ' "$REPO/contracts/capability.schema.md"
[ $? -ne 0 ];                             chk "the capability contract's example declares no domain field" $?

# =====================================================================================
t "domain contract: a domain is inert"
DD="$TMP/domains"; mkdir -p "$DD"
dom() { rm -f "$DD"/*.yaml; cat > "$DD/$1.yaml"; }

[ -f "$REPO/contracts/domain.schema.md" ];  chk "the domain contract has its own schema" $?
[ -x "$CLI/atlas-domain" ];               chk "the domain registry is executable" $?
out=$("$CLI/atlas" domain list 2>&1)
echo "$out" | grep -q 'domains'
chk "atlas domain is wired into the dispatcher" $?

# The shipped registry: two unrelated domains, both valid. One domain proves nothing about
# agnosticism; two unrelated ones are the actual evidence.
out=$("$CLI/atlas-domain" doctor 2>&1); rc=$?
echo "$out" | grep -q 'all domain declarations valid'
chk "the shipped domain declarations are valid" $?
[ "$rc" -eq 0 ];                          chk "  ...and doctor exits 0 (warnings are not failures)" $?
out=$("$CLI/atlas-domain" list 2>&1)
echo "$out" | grep -q 'software' && echo "$out" | grep -q 'customer-support'
chk "two unrelated domains are declared, not one" $?

# There is no third verb, and its absence is the contract.
out=$("$CLI/atlas-domain" deliver 2>&1); rc=$?
[ "$rc" -eq 2 ];                          chk "an execution verb is refused — list and doctor are the whole surface" $?
grep -Eqi 'def cmd_(deliver|invoke|run|execute|dispatch|plan)' "$CLI/atlas-domain"
[ $? -ne 0 ];                             chk "the domain registry implements no execution command" $?
grep -Eqi 'subprocess|os\.system|exec\(' "$CLI/atlas-domain"
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
echo "$out" | grep -q 'zzz-unknown-area: declaration valid'
chk "a domain and outcome Core has never heard of validate like any other" $?

dom mismatch <<'EOF'
domain: notmismatch
name: Mismatched
contract: 1
outcomes: { thing: { summary: s } }
EOF
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
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
  out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1); rc=$?
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
echo "$out" | grep -q 'never a sequence'
chk "an outcome may not name what follows it" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
outcomes: { thing: { summary: s, command: go } }
EOF
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1); rc=$?
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1); rc=$?
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
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
echo "$out" | grep -q 'is itself'
chk "a domain requiring itself is refused — and it is not a capability" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 9
outcomes: { thing: { summary: s } }
EOF
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
echo "$out" | grep -q 'DISABLED'
chk "an unsupported contract version is disabled, never partially honoured" $?

dom d1 <<'EOF'
domain: d1
name: D
contract: 1
outcomes: { thing: { summary: write the claude rules file } }
EOF
out=$(ATLAS_DOMAINS="$DD" "$CLI/atlas-domain" doctor 2>&1)
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
out=$(ATLAS_PLUGINS="$CF" "$CLI/atlas-capability" doctor 2>&1); rc=$?
echo "$out" | grep -q 'names an AI client'
chk "a capability naming an AI client is rejected" $?
echo "$out" | grep -q 'belongs in adapters/'
chk "  ...and is told where that belongs" $?
[ "$rc" -gt 0 ];                         chk "  ...as a hard failure" $?
rm -rf "$CF/x"

# =====================================================================================
t "boundary: executed is not verified, and invoke is not wired"
grep -q 'executed' "$REPO/contracts/capability.schema.md" && grep -q 'verified' "$REPO/contracts/capability.schema.md"
chk "the contract distinguishes executed from verified" $?
grep -q 'never implies' "$REPO/contracts/capability.schema.md"
chk "  ...explicitly, as a stated rule" $?
# Superseded by AIOS-007: invoke is wired. What must still hold is that it refuses
# cleanly for anything it cannot actually run, and writes no state while doing so.
out=$("$CLI/atlas-capability" invoke nosuchcap.build 2>&1); rc=$?
[ "$rc" -eq 4 ];                         chk "invoke refuses an unknown capability" $?
echo "$out" | grep -q 'unavailable';     chk "  ...as unavailable, before any authority check" $?
out=$("$CLI/atlas-capability" invoke browser.nosuchop 2>&1); rc=$?
[ "$rc" -eq 4 ];                         chk "invoke refuses an undeclared operation" $?
[ ! -e "$ATLAS_HOME/internal/config/capabilities.yaml" ]
chk "  ...and wrote no state nothing consumes" $?

# =====================================================================================
t "boundary: no client name leaked into the capability path of Core"
for f in atlas-capability; do
  grep -Eio 'playwright|chromium' "$CLI/$f" >/dev/null 2>&1
  [ $? -ne 0 ];                          chk "$f names no browser vendor" $?
done
# atlas-capability may name clients ONLY inside the rejection pattern that forbids them.
n=$(grep -c 'CLIENT_NAMES' "$CLI/atlas-capability")
[ "$n" -ge 2 ];                          chk "the client-name ban is a mechanical check, not prose" $?
hits=$(grep -Eio '\bclaude\b|\bcodex\b|\bgemini\b' "$CLI/atlas-capability" | wc -l | tr -d ' ')
inpat=$(grep -Eo 'claude\|claude-code\|codex\|cursor\|gemini\|opencode\|chatgpt' "$CLI/atlas-capability" | wc -l | tr -d ' ')
[ "$inpat" -ge 1 ];                      chk "  ...and the ban lists the client names it rejects" $?

# =====================================================================================
t "browser capability: manifest, dependencies and authority declarations"
BR="$REPO/capabilities/browser"
[ -f "$BR/capability.yaml" ];                 chk "the browser capability ships a manifest" $?
out=$("$CLI/atlas-capability" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "it validates against the capability contract" $?
echo "$out" | grep -q 'browser: manifest valid'; chk "  ...and is reported valid" $?
"$CLI/atlas-capability" list 2>&1 | grep -q 'browser'; chk "capability discovery finds it" $?
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
for f in atlas atlas-capability atlas-adapter ai-sync atlas-memory atlas-doctor atlas-init atlas-onboard; do
  grep -Eqi 'playwright|chromium|webkit|querySelector|page\.goto' "$CLI/$f"
  [ $? -ne 0 ];                           chk "Core tool $f names no browser technology" $?
done
grep -Eqi 'playwright|chromium' "$REPO/contracts/capability.schema.md"
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
AW="$TMP/authws"; ATLAS_HOME="$AW" "$CLI/atlas-init" >/dev/null 2>&1
grep -q '^default: observe' "$AW/internal/config/authority.yaml"
chk "a fresh workspace grants only observe" $?
out=$(ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.read --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "an observe operation is allowed by default" $?
out=$(ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.click --dry-run 2>&1); rc=$?
[ "$rc" -eq 5 ];                          chk "an execute operation is denied by default" $?
echo "$out" | grep -q 'never with a flag';chk "  ...and points at the grant file, not a flag" $?
out=$(ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.submit --dry-run </dev/null 2>&1); rc=$?
[ "$rc" -eq 5 ];                          chk "an approval operation is denied with no terminal" $?
# Grant execute; click becomes allowed, submit still does not.
python3 - "$AW" <<'PYEOF'
import sys,pathlib
f=pathlib.Path(sys.argv[1])/"internal/config/authority.yaml"
f.write_text(f.read_text().replace("capabilities: {}","capabilities:\n  browser: execute"))
PYEOF
ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.click --dry-run >/dev/null 2>&1
chk "an explicit grant allows the operation" $?
ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.submit --dry-run </dev/null >/dev/null 2>&1
[ $? -eq 5 ];                             chk "  ...and does not leak into the rung above it" $?
# No bypass flags anywhere in Core.
grep -Eq '\-\-force|\-\-unsafe|\-\-god-mode|\-\-bypass|allowEverything' "$CLI/atlas-capability"
[ $? -ne 0 ];                             chk "Core offers no force/unsafe/bypass flag" $?
# autonomous is refused, never granted.
python3 - "$AW" <<'PYEOF'
import sys,pathlib
f=pathlib.Path(sys.argv[1])/"internal/config/authority.yaml"
f.write_text(f.read_text().replace("  browser: execute","  browser: autonomous"))
PYEOF
out=$(ATLAS_HOME="$AW" "$CLI/atlas-capability" invoke browser.click --dry-run 2>&1)
echo "$out" | grep -q "granted 'observe'"
chk "an autonomous grant is not honoured — it falls back to the floor" $?

# =====================================================================================
t "verification: executed is never verified by assertion"
VB="$REPO/capabilities/browser"
# A result that simply claims success must not verify.
out=$(cd "$VB" && echo '{"ok":true,"operation":"submit","verified":true,"note":"I submitted it"}' \
      | ATLAS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify submit 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "a self-reported success does not verify" $?
# A failed operation cannot verify.
out=$(cd "$VB" && echo '{"ok":false}' | ATLAS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify navigate 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "a failed operation does not verify" $?
# Verification with no session cannot pass.
out=$(cd "$VB" && echo '{"ok":true,"operation":"read"}' | ATLAS_BROWSER_RUNTIME="$TMP/novr" ./browser-verify read 2>&1); rc=$?
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
grep -q 'cwd=str(d)' "$CLI/atlas-capability";  chk "Core runs a capability inside its own directory" $?
grep -q 'shell=True' "$CLI/atlas-capability"
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
  br() { (cd "$VB" && echo "$2" | ATLAS_BROWSER_RUNTIME="$RT" ./browser "$1"); }
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
  (cd "$VB" && printf '%s' "$res" | ATLAS_BROWSER_RUNTIME="$RT" ./browser-verify submit >/dev/null 2>&1)
  chk "  ...and live browser state VERIFIES it" $?
  # The same submit with a false expectation must not verify.
  (cd "$VB" && printf '%s' "$res" | sed 's/d.html"}}/nope"}}/' \
     | ATLAS_BROWSER_RUNTIME="$RT" ./browser-verify submit >/dev/null 2>&1)
  [ $? -ne 0 ];                           chk "  ...and a false expectation does NOT verify" $?
  br close '{}' | grep -q '"ok": true';   chk "the session closes and releases the browser" $?
  [ ! -f "$RT/session.json" ];            chk "  ...leaving no session behind" $?
else
  printf '  %sSKIP%s browser provider unavailable on this machine\n' "$D" "$X"
fi

# =====================================================================================
t "run: create requires an explicit, finite budget and scope"
RW="$TMP/runws"; ATLAS_HOME="$RW" "$CLI/atlas-init" >/dev/null 2>&1
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" create --scope 'browser.read' 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "refuses to create with no --max-steps" $?
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" create --max-steps 3 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "refuses to create with no --scope" $?
grep -Eq -- '--unlimited|--no-limit|autonomous=true' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "no unlimited/bypass mode exists in the code" $?
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" create --max-steps 3 --scope 'browser.read,browser.navigate' --task AIOS-TEST 2>&1)
echo "$out" | grep -q 'created';          chk "creates a run with a finite budget and scope" $?
RUN_ID=$(echo "$out" | grep -oE 'run-[0-9a-f-]+' | head -1)
[ -n "$RUN_ID" ];                         chk "  ...and prints its id" $?
[ -f "$RW/runtime/runs/$RUN_ID.json" ];   chk "  ...persisted under runtime/, not tasks/ or memory" $?

# =====================================================================================
t "run: scope — out-of-scope capability/operation is refused, run stays continue"
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" step "$RUN_ID" browser.click --dry-run 2>&1); rc=$?
echo "$out" | grep -q 'outside this run.s scope';  chk "an out-of-scope operation is refused" $?
[ "$rc" -ne 0 ];                          chk "  ...as a non-zero exit" $?
rec="$RW/runtime/runs/$RUN_ID.json"
grep -q '"status": "continue"' "$rec";    chk "  ...and the run itself is untouched — still continue" $?
grep -q '"steps_used": 0' "$rec";         chk "  ...a Run-local refusal never consumes budget" $?

# =====================================================================================
t "run: authority — run scope can only restrict, never elevate, the user's grant"
grep -q '^default: observe' "$RW/internal/config/authority.yaml"
chk "fresh workspace still grants only observe" $?
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" step "$RUN_ID" browser.read --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                          chk "an in-scope, observe-level op is allowed" $?
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" step "$RUN_ID" browser.navigate --dry-run 2>&1); rc=$?
echo "$out" | grep -q "needs 'execute'; granted 'observe'"
chk "an in-scope op still needs the SAME authority invoke would require" $?
[ "$rc" -eq 6 ];                          chk "  ...and the run blocks rather than silently downgrading" $?
grep -Eq -- '--force|--unsafe|--bypass|allowEverything|authority\.yaml.*=.*open\(.*.w.' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "atlas-run contains no bypass flag and never writes authority.yaml" $?
grep -q 'stdin=subprocess.DEVNULL' "$CLI/atlas-run"
chk "every step's stdin is closed — a Run can never see a terminal to approve through" $?

# =====================================================================================
t "run: approval — execute-with-approval is never silently satisfied"
ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" create --max-steps 3 --scope 'browser.submit' >/tmp/aios-run-approval.out 2>&1
RUN_A=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-approval.out | head -1)
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" step "$RUN_A" browser.submit --dry-run </dev/null 2>&1); rc=$?
echo "$out" | grep -q "needs-approval";   chk "an approval-gated op moves the run to needs-approval" $?
[ "$rc" -eq 5 ];                          chk "  ...as its own distinct exit code" $?
grep -q '"status": "needs-approval"' "$RW/runtime/runs/$RUN_A.json"
chk "  ...and the run record says so" $?
out=$(ATLAS_HOME="$RW" ATLAS_HOME="$RW" "$CLI/atlas-run" step "$RUN_A" browser.read --dry-run 2>&1); rc=$?
echo "$out" | grep -q 'refused';          chk "needs-approval is terminal — no further step is taken" $?
rm -f /tmp/aios-run-approval.out

# =====================================================================================
t "run: verification — an executed-but-unverified step never becomes 'completed'"
grep -q "deterministic check passed" "$CLI/atlas-run"
chk "completion is only ever tied to invoke's own 'verified' text, never asserted" $?
grep -Eq 'status.*=.*.completed.*executed' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "no code path marks 'executed' alone as completed" $?

# =====================================================================================
t "run: budget — a step beyond max_steps is refused and the run ends"
BW="$TMP/budgetws"; ATLAS_HOME="$BW" "$CLI/atlas-init" >/dev/null 2>&1
ATLAS_HOME="$BW" ATLAS_HOME="$BW" "$CLI/atlas-run" create --max-steps 1 --scope 'browser.navigate' >/tmp/aios-run-budget.out 2>&1
RUN_B=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-budget.out | head -1)
ATLAS_HOME="$BW" ATLAS_HOME="$BW" "$CLI/atlas-run" step "$RUN_B" browser.navigate --json '{"url":"http://example.com"}' >/dev/null 2>&1
grep -q '"steps_used": 1' "$BW/runtime/runs/$RUN_B.json"
chk "the one permitted step consumed the budget" $?
out=$(ATLAS_HOME="$BW" ATLAS_HOME="$BW" "$CLI/atlas-run" step "$RUN_B" browser.navigate --json '{}' 2>&1); rc=$?
echo "$out" | grep -qE 'blocked|budget exhausted|not .continue.'
chk "a step beyond the budget is refused" $?
[ "$rc" -ne 0 ];                          chk "  ...as a non-zero exit" $?
rm -f /tmp/aios-run-budget.out

# =====================================================================================
t "run: reset protection — nothing in this CLI can grow or reset max_steps"
n=$(grep -c 'max_steps' "$CLI/atlas-run")
[ "$n" -gt 0 ];                           chk "max_steps exists" $?
! grep -qE '^CMDS = .*"(reset|extend|edit|update)"' "$CLI/atlas-run"
chk "no reset/extend/edit/update subcommand exists" $?
grep -c '"create": cmd_create' "$CLI/atlas-run" | grep -q '^1$'
chk "max_steps is set exactly once, at create" $?

# =====================================================================================
t "run: task isolation — Core never reads or writes tasks/"
grep -Eq 'tasks/|open\(.*task\.md|task_id\].*read_text' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "atlas-run contains no path into tasks/" $?
grep -q 'opaque' "$CLI/atlas-run";        chk "task_id is documented as opaque, never parsed" $?

# =====================================================================================
t "run: persistence isolation — run state lives only under runtime/"
# T-021: deliberately Atlas-canonical, not the ATLAS_HOME-compat resolver 13+ other
# commands still use — see the comment above _ATLAS_HOME in cli/atlas-run.
grep -q 'RUNS_DIR = _ATLAS_HOME / "runtime" / "runs"' "$CLI/atlas-run"
chk "run records are rooted under runtime/runs/" $?
grep -Eq '02-personal|05-knowledge|memory/|knowledge/' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "atlas-run writes no durable workspace state" $?

# =====================================================================================
t "run: determinism — the same run, the same step, refused the same way twice"
DW="$TMP/detws"; ATLAS_HOME="$DW" "$CLI/atlas-init" >/dev/null 2>&1
ATLAS_HOME="$DW" ATLAS_HOME="$DW" "$CLI/atlas-run" create --max-steps 5 --scope 'browser.read' >/tmp/aios-run-det.out 2>&1
RUN_D=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-det.out | head -1)
out1=$(ATLAS_HOME="$DW" ATLAS_HOME="$DW" "$CLI/atlas-run" step "$RUN_D" browser.click --dry-run 2>&1); rc1=$?
out2=$(ATLAS_HOME="$DW" ATLAS_HOME="$DW" "$CLI/atlas-run" step "$RUN_D" browser.click --dry-run 2>&1); rc2=$?
[ "$rc1" -eq "$rc2" ];                    chk "the same out-of-scope call refuses identically twice" $?
[ "$out1" = "$out2" ];                    chk "  ...with byte-identical output" $?
rm -f /tmp/aios-run-det.out

# =====================================================================================
t "run: not an orchestrator — no decision-making vocabulary in this file"
grep -Eiq '\bnext_action\b|\bplan\(|\bdecide_capability\b|\bchoose_operation\b' "$CLI/atlas-run"
[ $? -ne 0 ];                             chk "atlas-run contains no planning/decision logic" $?

# =====================================================================================
if (cd "$REPO/capabilities/browser" && echo '{}' | ./browser detect >/dev/null 2>&1); then
t "run: no-progress — an identical unverified step repeated 3x blocks the run"
NW="$TMP/noprogws"; ATLAS_HOME="$NW" "$CLI/atlas-init" >/dev/null 2>&1
python3 - "$NW" <<'PYEOF'
import sys, pathlib
f = pathlib.Path(sys.argv[1]) / "internal/config/authority.yaml"
f.write_text(f.read_text().replace("capabilities: {}", "capabilities:\n  browser: execute"))
PYEOF
NWEB="$TMP/noprog-web"; mkdir -p "$NWEB"
cat > "$NWEB/f.html" <<'HTMLEOF'
<html><body><h1 id="h">Exam</h1><button id="b" type="button">Click</button></body></html>
HTMLEOF
export ATLAS_BROWSER_RUNTIME="$TMP/noprog-runtime"
ATLAS_HOME="$NW" ATLAS_HOME="$NW" "$CLI/atlas-run" create --max-steps 10 \
  --scope 'browser.open,browser.navigate,browser.click,browser.close' >/tmp/aios-run-noprog.out 2>&1
RUN_N=$(grep -oE 'run-[0-9a-f-]+' /tmp/aios-run-noprog.out | head -1)
ATLAS_HOME="$NW" ATLAS_HOME="$NW" "$CLI/atlas-run" step "$RUN_N" browser.open --json '{}' >/dev/null 2>&1
ATLAS_HOME="$NW" ATLAS_HOME="$NW" "$CLI/atlas-run" step "$RUN_N" browser.navigate --json "{\"url\":\"file://$NWEB/f.html\"}" >/dev/null 2>&1
for i in 1 2 3; do
  out=$(ATLAS_HOME="$NW" ATLAS_HOME="$NW" "$CLI/atlas-run" step "$RUN_N" browser.click --json '{"selector":"#b"}' 2>&1)
done
echo "$out" | grep -q 'no-progress';      chk "the 3rd identical unverified click blocks the run" $?
grep -q '"status": "blocked"' "$NW/runtime/runs/$RUN_N.json"
chk "  ...recorded in the run itself" $?
out=$(ATLAS_HOME="$NW" ATLAS_HOME="$NW" "$CLI/atlas-run" step "$RUN_N" browser.click --json '{"selector":"#b"}' 2>&1); rc=$?
[ "$rc" -ne 0 ];                          chk "  ...and a 4th attempt is refused, not retried" $?
ATLAS_HOME="$NW" ATLAS_PLUGINS="$REPO/capabilities" "$CLI/atlas-capability" invoke browser.close --json '{}' >/dev/null 2>&1
rm -f /tmp/aios-run-noprog.out
else
  printf '  %sSKIP%s run: no-progress test needs a working browser provider\n' "$D" "$X"
fi

# =====================================================================================
t "run: dispatcher and schema exist and are wired"
# T-031: atlas is the canonical entry point that carries the documentation banner; atlas is
# now a thin compatibility alias (single exec line) with no banner text of its own.
grep -q 'atlas run' "$CLI/atlas";          chk "atlas run is a documented subcommand" $?
grep -q '|run|' "$CLI/atlas";              chk "  ...and dispatches to atlas-run" $?
[ -f "$REPO/contracts/run.schema.md" ];      chk "contracts/run.schema.md exists" $?
grep -q 'not an agent' "$REPO/contracts/run.schema.md"
chk "  ...and states the boundary: not an agent/orchestrator/planner" $?

# =====================================================================================
t "handoff: dispatcher exposes atlas handoff"
# T-031: same rationale as the run check above — canonical banner text now lives in atlas.
grep -q 'atlas handoff' "$CLI/atlas";      chk "atlas handoff is a documented subcommand" $?
grep -qE '\|handoff[|)]' "$CLI/atlas";          chk "  ...and dispatches to atlas-handoff" $?
[ -x "$CLI/atlas-handoff" ];               chk "cli/atlas-handoff exists and is executable" $?

# =====================================================================================
t "handoff: prepare writes one task-local Markdown record"
HW="$TMP/handoff-ws"; ATLAS_HOME="$HW" "$CLI/atlas-init" >/dev/null 2>&1
mkdir -p "$HW/tasks/AIOS-TEST"
cat > "$HW/tasks/AIOS-TEST/task.md" <<'TASKEOF'
---
id: AIOS-TEST
title: A durable task the handoff is bound to
project: atlas
---
TASKEOF
# Everything outside tasks/ is fingerprinted first: a record engine that writes one file
# beside one task must leave the rest of the workspace byte-identical.
hw_outside() { (cd "$HW" && find . -path ./tasks -prune -o -type f -exec shasum {} \; | sort | shasum); }
before=$(hw_outside)
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review \
        --scope 'cli/atlas-handoff, tests/test-contract.sh' \
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
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff show AIOS-TEST "$HID" 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "show exits 0" $?
# T-048: show writes the raw record verbatim, then appends one derived-only
# "source client/session" footer line (blank line + the footer) — never written back
# to the record itself. Strip exactly those two trailing lines before comparing.
out_without_footer=$(printf '%s' "$out" | sed '$d' | sed '$d')
[ "$out_without_footer" = "$(cat "$HREC")" ]
chk "  ...and prints the record verbatim, plus the T-048 source footer" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff list AIOS-TEST 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "list exits 0" $?
echo "$out" | grep -q "$HID";              chk "  ...and finds the record it just wrote" $?
echo "$out" | grep -q 'codex';             chk "  ...with its destination" $?
[ "$before" = "$(hw_outside)" ];           chk "show and list wrote nothing" $?

# =====================================================================================
t "handoff: draft records cannot be approved or sent"
SEED="$TMP/seed-reply.md"; echo "a reply that is never attached" > "$SEED"
rec_before=$(shasum < "$HREC"); ws_before=$(cd "$HW" && find . -type f | sort | shasum)
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST "$HID" --gate review --to codex \
  --scope 'cli/atlas-handoff, tests/test-contract.sh' --owner-words 'Owner approves this fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "approve refuses a draft record" $?
echo "$out" | grep -q 'waiting-owner';    chk "  ...and says only waiting-owner can be approved" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff send AIOS-TEST "$HID" 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "send refuses a record with no matching approval" $?
echo "$out" | grep -q "not 'approved'"; chk "  ...naming the status it refused on" $?
echo "$out" | grep -q 'nothing was sent';  chk "  ...and saying nothing was sent" $?
echo "$out" | grep -Eiq 'transport|handoff-transports'
[ $? -ne 0 ];                            chk "  ...refused before any transport was consulted" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff receive AIOS-TEST "$HID" \
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
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing task id refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare ../escape --to codex --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "invalid task id refused (no path escape)" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare NO-SUCH --to codex --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing task directory refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --to refused" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to nobody --gate review --scope x 2>&1)
[ $? -ne 0 ];                              chk "unknown destination client refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to 'codex,claude-code' --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "more than one destination refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --to gemini --gate review --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "  ...including a repeated --to" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --gate refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate anything --scope x >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a gate outside the template vocabulary refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review >/dev/null 2>&1
[ $? -ne 0 ];                              chk "missing --scope refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review --scope '   ' >/dev/null 2>&1
[ $? -ne 0 ];                              chk "empty --scope refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review --scope x --status approved >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a status V2 may not write refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review --scope x --id "$HID" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a duplicate handoff id refused" $?
[ "$rec_before" = "$(shasum < "$HREC")" ]; chk "  ...and the existing record untouched" $?
# Assembled from two adjacent quoted halves on purpose: a token-shaped literal sitting in
# a public test file would be a real finding, and atlas-privacy-scan would be right to
# flag it. The shell joins them; the scanner reading the file text never sees `ghp_`.
FAKE_TOKEN="gh"'p_0123456789abcdefghijklmnop'
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to codex --gate review --scope x \
  --summary "credential $FAKE_TOKEN" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "a credential-shaped value in the packet refused" $?
[ "$(find "$HW/tasks/AIOS-TEST" -name 'handoff-*.md' | wc -l | tr -d ' ')" = "$n_before" ]
chk "fourteen refusals, zero records written" $?

# =====================================================================================
t "handoff: a second record is additive, not an overwrite"
ATLAS_HOME="$HW" "$CLI/atlas" handoff prepare AIOS-TEST --to claude-code --gate next-step \
  --scope 'V3 approval gate' --status waiting-owner --id trial-a >/dev/null 2>&1
[ $? -eq 0 ];                              chk "a second prepare exits 0" $?
[ -f "$HW/tasks/AIOS-TEST/handoff-trial-a.md" ]; chk "  ...and writes its own file" $?
[ "$rec_before" = "$(shasum < "$HREC")" ]; chk "  ...leaving the first record byte-identical" $?
grep -q '^status: waiting-owner$' "$HW/tasks/AIOS-TEST/handoff-trial-a.md"
chk "  ...with waiting-owner as the other status V2 may write" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff list AIOS-TEST 2>&1)
echo "$out" | grep -q trial-a && echo "$out" | grep -q "$HID"
chk "list shows both, found by globbing the task directory" $?

# =====================================================================================
t "handoff: approve records explicit owner words and exact tuple only"
AREC="$HW/tasks/AIOS-TEST/handoff-trial-a.md"
approval_before=$(shasum < "$AREC"); ws_before=$(cd "$HW" && find . -type f | sort | shasum)
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate review \
  --to claude-code --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched gate refused" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
  --to codex --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched destination refused" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'other scope' --owner-words 'Owner approves V3 fixture' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval with mismatched scope refused" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "approval without owner words refused" $?
ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' --owner-words "$FAKE_TOKEN" >/dev/null 2>&1
[ $? -ne 0 ];                              chk "credential-shaped owner words refused" $?
[ "$approval_before" = "$(shasum < "$AREC")" ]; chk "all bad approvals leave the record byte-identical" $?
[ "$ws_before" = "$(cd "$HW" && find . -type f | sort | shasum)" ]
chk "  ...and write no side files" $?

out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
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
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff approve AIOS-TEST trial-a --gate next-step \
  --to claude-code --scope 'V3 approval gate' --owner-words 'Owner approves V3 fixture again' 2>&1); rc=$?
[ "$rc" -ne 0 ];                           chk "a second approval is refused, not overwritten" $?
[ "$approved_before" = "$(shasum < "$AREC")" ]; chk "  ...leaving owner words byte-identical" $?
out=$(ATLAS_HOME="$HW" "$CLI/atlas" handoff send AIOS-TEST trial-a --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "send --dry-run exits 0 once the approval matches" $?
echo "$out" | grep -q 'dry run';           chk "  ...and says it is a dry run" $?
[ "$approved_before" = "$(shasum < "$AREC")" ]; chk "  ...and still writes nothing" $?

# =====================================================================================
t "handoff: the sender has exactly one way out, and it is fenced"
# V2 and V3 asserted this file could not spawn anything at all. V4 gives it one call, so
# the invariant moves: not "no subprocess" but "one subprocess, no shell, no retry".
grep -Eq '^[[:space:]]*(import|from)[[:space:]]+[A-Za-z0-9_, ]*\b(socket|http|urllib|smtplib|ftplib|telnetlib|asyncio|requests|ssl)\b' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "imports nothing that could open a network connection" $?
grep -Eq 'os\.(system|popen|exec[lv]|spawn)|urlopen|pbcopy|pbpaste|osascript|xdg-open|webbrowser' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no shell-out, clipboard or app-open call" $?
grep -Eq '[,(][[:space:]]*shell[[:space:]]*=[[:space:]]*True' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "never shell=True — the packet can never be a command" $?
# Three call sites now, and the invariant is about what they can reach, not how many
# there are: the local read-only resolver that says where a ticket lives, run_transport_
# subprocess (T-051-S7's shared bounded-call helper, also used by `mission execute` in
# cli/atlas_mission.py), and the one that may leave this machine unmonitored (`send`'s own
# uncaptured call). Anything beyond those three is a new way out.
[ "$(grep -c 'subprocess\.run(' "$CLI/atlas-handoff")" = "3" ]
chk "exactly three subprocess.run call sites, and no more" $?
grep -q 'subprocess.run(argv, input=packet' "$CLI/atlas-handoff"
chk "  ...one is the transport, taking a list argv and the packet on stdin" $?
grep -q 'subprocess.run(\[str(RESOLVER), "ticket", task_id\]' "$CLI/atlas-handoff"
chk "  ...the other is the local path resolver, and it only reads" $?
grep -Eq 'timeout=timeout' "$CLI/atlas-handoff"; chk "  ...under a timeout" $?
grep -Eq 'os\.fork|threading\.|multiprocessing\.|Thread\(|Timer\(|nohup|setsid' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no thread, fork, timer or background worker" $?
grep -Eiq 'mcp__|mcp_servers|claude\.ai|api\.anthropic|api\.openai|https?://|wss?://' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no MCP server, connector or AI endpoint" $?
grep -Eq 'handoffs/|"handoffs"' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no path to a global handoffs/ directory" $?
grep -Eq 'def cmd_receive' "$CLI/atlas-handoff"
chk "receive is implemented" $?
grep -Eq 'while True|time\.sleep\(|\.retry|backoff[[:space:]]*=' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no sleep, backoff or polling primitive" $?
# "Not retried" is structural, not textual: no call out of this file may sit inside any
# loop. A grep for the word "retry" would only find the comment promising there isn't one.
python3 - "$CLI/atlas-handoff" <<'PYEOF'
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
grep -q 'TRANSPORTS = Path(os.environ.get("ATLAS_HANDOFF_TRANSPORTS"' "$CLI/atlas-handoff"
chk "the transport is read from a declared registry, never synthesised" $?
grep -Eiq '\bnext_action\b|def (plan|decide|orchestrat|dispatch|route)' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "no planning, orchestration or dispatch logic" $?
# `tickets` has no single root once records live per project, so a handoff may not join a path
# onto one. It asks the resolver for the item, by id, and builds no task path of its own.
grep -q 'RESOLVER = REPO / "cli" / "atlas-paths"' "$CLI/atlas-handoff"
chk "records are bound to the resolver's answer for the item id" $?
grep -Eq '(ATLAS_HOME|HOME)[^\n]*/[[:space:]]*"tasks"|ATLAS_HOME[^\n]*tasks/' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "  ...and no tasks/ path is constructed anywhere in the file" $?
grep -q 'TASKS = ' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "  ...and no single ticket root is cached at import time" $?

# =====================================================================================
t "handoff send: fixtures"
SW="$TMP/send-ws"; ATLAS_HOME="$SW" "$CLI/atlas-init" >/dev/null 2>&1
mkdir -p "$SW/tasks/AIOS-SEND"
cat > "$SW/tasks/AIOS-SEND/task.md" <<'TASKEOF'
---
id: AIOS-SEND
title: The send fixture task
project: atlas
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
  ATLAS_HOME="$SW" PATH="$FB:$PATH" ATLAS_HANDOFF_TRANSPORTS="$reg" \
    FAKE_CLIENT_SINK="$TMP/sink.txt" "$CLI/atlas" handoff send AIOS-SEND "$@" 2>&1
}
mkh() { ATLAS_HOME="$SW" "$CLI/atlas" handoff prepare AIOS-SEND --to "$2" --gate "$3" \
          --scope "$4" --status waiting-owner --id "$1" >/dev/null 2>&1; }
apr() { ATLAS_HOME="$SW" "$CLI/atlas" handoff approve AIOS-SEND "$1" --gate "$3" --to "$2" \
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
    "_a", str(repo / "cli" / "atlas-adapter")))
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
    "_a", str(repo / "cli" / "atlas-adapter")))
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
out=$(ATLAS_HOME="$SW" "$CLI/atlas" handoff send AIOS-SEND blocked --dry-run 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "against the shipped registry, dry run still works" $?
if command -v codex >/dev/null 2>&1; then
  echo "$out" | grep -q 'command:';         chk "  ...and shows the verified transport command when codex is installed" $?
  echo "$out" | grep -q 'packet on stdin';  chk "  ...with the packet on stdin" $?
else
  echo "$out" | grep -q 'unavailable';      chk "  ...and reports unavailable when codex is not installed" $?
fi

# =====================================================================================
t "handoff receive: fixtures"
RW="$TMP/recv-ws"; ATLAS_HOME="$RW" "$CLI/atlas-init" >/dev/null 2>&1
mkdir -p "$RW/tasks/AIOS-RECV"
cat > "$RW/tasks/AIOS-RECV/task.md" <<'TASKEOF'
---
id: AIOS-RECV
title: The receive fixture task
project: atlas
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
  ATLAS_HOME="$RW" "$CLI/atlas" handoff prepare AIOS-RECV --to codex --gate review \
    --scope "scope $1" --status waiting-owner --id "$1" >/dev/null 2>&1
  ATLAS_HOME="$RW" "$CLI/atlas" handoff approve AIOS-RECV "$1" --gate review --to codex \
    --scope "scope $1" --owner-words "Owner approves $1" >/dev/null 2>&1
  ATLAS_HOME="$RW" PATH="$RB:$PATH" ATLAS_HANDOFF_TRANSPORTS="$TMP/tr-recv.yaml" \
    "$CLI/atlas" handoff send AIOS-RECV "$1" >/dev/null 2>&1
}
hrecv() { ATLAS_HOME="$RW" "$CLI/atlas" handoff receive AIOS-RECV "$@" 2>&1; }
rw_fp() { (cd "$RW" && find . -type f -exec shasum {} \; | sort | shasum); }
rw_fp_but() { (cd "$RW" && find . -type f ! -name "handoff-$1.md" -exec shasum {} \; | sort | shasum); }
for id in good twice wrongfrom badfile reviewed status; do rsend "$id"; done
ATLAS_HOME="$RW" "$CLI/atlas" handoff prepare AIOS-RECV --to codex --gate review \
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
ATLAS_HOME="$RW" "$CLI/atlas" handoff prepare AIOS-RECV --to codex --gate review \
  --scope 'نطاق عربي' --status waiting-owner --id arabic >/dev/null 2>&1
ATLAS_HOME="$RW" "$CLI/atlas" handoff approve AIOS-RECV arabic --gate review --to codex \
  --scope 'نطاق عربي' --owner-words 'وافقت، أرسلها إلى Codex.' >/dev/null 2>&1
grep -q 'owner_words: "وافقت، أرسلها إلى Codex."' "$AW"
chk "non-ASCII owner words are stored readable, not as \\uXXXX escapes" $?
grep -q 'scope: "نطاق عربي"' "$AW";        chk "  ...and so is a non-ASCII scope" $?
grep -Eq '\\\\u0648|\\\\u06' "$AW"
[ $? -ne 0 ];                              chk "  ...with no escape sequence anywhere in the record" $?
ATLAS_HOME="$RW" PATH="$RB:$PATH" ATLAS_HANDOFF_TRANSPORTS="$TMP/tr-recv.yaml" \
  "$CLI/atlas" handoff send AIOS-RECV arabic >/dev/null 2>&1
[ $? -eq 0 ];                              chk "and the record still parses back for send" $?
printf 'المراجعة تمت. لا ملاحظات.\n' > "$TMP/reply-ar.md"
hrecv arabic --from codex --file "$TMP/reply-ar.md" >/dev/null 2>&1
[ $? -eq 0 ];                              chk "  ...and for receive" $?
grep -q 'المراجعة تمت. لا ملاحظات.' "$AW"; chk "an Arabic reply is attached readable" $?

# =====================================================================================
t "handoff receive: it has no way to act on what it received"
python3 - "$CLI/atlas-handoff" <<'PYEOF'
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
python3 - "$CLI/atlas-handoff" <<'PYEOF'
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
grep -q 'def cmd_receive' "$CLI/atlas-handoff"; chk "receive is implemented, not reserved" $?
grep -Eq 'RESERVED|cmd_reserved' "$CLI/atlas-handoff"
[ $? -ne 0 ];                              chk "  ...and the reserved-command scaffolding is gone" $?
grep -q 'handoff .*receive' "$CLI/atlas"; chk "receive is a documented subcommand" $?

# =====================================================================================
t "the plugin -> capability rename keeps its compatibility window open"
# The surface was renamed on 2026-09-03. Every old spelling must keep working for one
# version, and each of these is a promise made in schemas/capability.schema.md. When the
# owner decides to close the window, these are the tests that must be deleted on purpose.

# --- the current names ----------------------------------------------------------------
"$CLI/atlas" capability list >/dev/null 2>&1
chk "atlas capability list works" $?
"$CLI/atlas" capability doctor >/dev/null 2>&1
chk "atlas capability doctor works" $?
[ -d "$REPO/capabilities" ];               chk "the capability registry is capabilities/" $?
[ -f "$REPO/capabilities/browser/capability.yaml" ]
chk "  ...and the shipped manifest is capability.yaml" $?
[ -f "$REPO/contracts/capability.schema.md" ]
chk "the capability contract is contracts/capability.schema.md" $?
[ -x "$CLI/atlas-capability" ];            chk "cli/atlas-capability is the real command" $?

# --- the compatibility names ----------------------------------------------------------
"$CLI/atlas" plugin list >/dev/null 2>&1
chk "atlas plugin list still works (alias)" $?
"$CLI/atlas" plugin doctor >/dev/null 2>&1
chk "atlas plugin doctor still works (alias)" $?
[ -x "$CLI/atlas-plugin" ];                chk "cli/atlas-plugin still exists as a shim" $?
newout=$("$CLI/atlas" capability list 2>&1)
oldout=$("$CLI/atlas" plugin list 2>&1)
[ "$newout" = "$oldout" ];                 chk "  ...and the alias produces identical output" $?
[ ! -e "$REPO/plugins" ];                  chk "plugins/ is not required for a new install" $?

# --- both env vars ----------------------------------------------------------------------
ATLAS_CAPABILITIES="$REPO/capabilities" "$CLI/atlas" capability doctor >/dev/null 2>&1
chk "ATLAS_CAPABILITIES points the registry" $?
ATLAS_PLUGINS="$REPO/capabilities" "$CLI/atlas" capability doctor >/dev/null 2>&1
chk "ATLAS_PLUGINS is still honoured as a fallback" $?
# The new name wins when both are set, so a stale old value cannot quietly take over.
EMPTYREG2="$TMP/emptyreg2"; mkdir -p "$EMPTYREG2"
out=$(ATLAS_CAPABILITIES="$REPO/capabilities" ATLAS_PLUGINS="$EMPTYREG2" \
      "$CLI/atlas" capability list 2>&1)
echo "$out" | grep -q 'browser';           chk "  ...and ATLAS_CAPABILITIES wins when both are set" $?

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
out=$(ATLAS_CAPABILITIES="$MF" "$CLI/atlas" capability list 2>&1)
echo "$out" | grep -q 'newname';           chk "capability.yaml is read" $?
echo "$out" | grep -q 'oldname';           chk "plugin.yaml is still read" $?
# The manifest KEY stays `plugin:` under contract 1 — renaming it is a contract 2 change.
grep -q '^plugin: browser' "$REPO/capabilities/browser/capability.yaml"
chk "the manifest key is still plugin: under contract 1" $?
out=$(ATLAS_CAPABILITIES="$MF" "$CLI/atlas" capability doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "  ...and both manifests validate" $?

# --- both filenames at once -------------------------------------------------------------
# Identical content is the harmless state a migration passes through: the new name wins.
BOTH="$TMP/manifest-both"; mkdir -p "$BOTH/twin"
manifest twin > "$BOTH/twin/capability.yaml"
cp "$BOTH/twin/capability.yaml" "$BOTH/twin/plugin.yaml"
out=$(ATLAS_CAPABILITIES="$BOTH" "$CLI/atlas" capability doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                           chk "identical capability.yaml and plugin.yaml resolve to one manifest" $?
# Differing content has no correct guess, so it is reported and nothing is merged.
printf 'plugin: twin\nname: DIFFERENT\ncontract: 1\ncapability: { authority: observe }\n' \
  > "$BOTH/twin/plugin.yaml"
out=$(ATLAS_CAPABILITIES="$BOTH" "$CLI/atlas" capability doctor 2>&1); rc=$?
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
"$CLI/atlas" domain doctor >/dev/null 2>&1
chk "domain declarations still validate against the renamed registry" $?
# domains/customer-support.yaml requires browser: it must still RESOLVE, not just parse.
out=$("$CLI/atlas" domain doctor 2>&1)
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
"$CLI/atlas-privacy-scan" --quiet "$REPO" >/dev/null 2>&1
chk "privacy-scan finds its allowlist under governance/" $?
grep -q 'governance/policies/privacy-allowlist.txt' "$CLI/atlas-privacy-scan"
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
# that must never be resolved by guessing. See cli/atlas-paths.
PA="$CLI/atlas-paths"
[ -x "$PA" ];                             chk "cli/atlas-paths exists and is executable" $?
for r in memory knowledge projects tickets rules runtime \
         config policies daily templates skills agents helpers schemas professional; do
  "$PA" layout "$r" >/dev/null 2>&1;      chk "  declares the '$r' root" $?
done
"$PA" layout nonesuch >/dev/null 2>&1
[ $? -eq 2 ];                             chk "an unknown root is refused, never invented" $?

# =====================================================================================
t "private path compatibility: old path, new path, neither"
PW="$TMP/paths"; mkdir -p "$PW"
export ATLAS_HOME="$PW"

mkdir -p "$PW/user/05-knowledge"
[ "$("$PA" layout knowledge)" = "old" ];                chk "old path only -> layout old" $?
[ "$("$PA" get knowledge)" = "$PW/user/05-knowledge" ]; chk "  ...and resolves to the old path" $?

mkdir -p "$PW/personal/memory"
[ "$("$PA" layout memory)" = "new" ];                   chk "new path only -> layout new" $?
[ "$("$PA" get memory)" = "$PW/personal/memory" ];      chk "  ...and resolves to the new path" $?

[ "$("$PA" layout projects)" = "none" ];                chk "neither path -> layout none" $?
[ "$("$PA" get projects)" = "$PW/projects" ]
chk "  ...and resolves to the new layout init now creates" $?

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
# tasks/ does not survive as one directory — it becomes per-project tickets/. Handing a
# caller the first match would be a guess dressed as an answer.
PW2="$TMP/paths-work"; mkdir -p "$PW2/projects/atlas/tickets" "$PW2/projects/rccm/tickets"
out=$(ATLAS_HOME="$PW2" "$PA" get tickets 2>&1); rc=$?
[ "$rc" -eq 4 ];                             chk "the new layout has no single ticket root -> exit 4" $?
echo "$out" | grep -q "no single root";      chk "  ...and says why" $?
[ "$(ATLAS_HOME="$PW2" "$PA" layout tickets)" = "new" ]
chk "  ...while still reporting the layout it found" $?

# =====================================================================================
t "private path compatibility: a marked pilot mirror is not a move"
# Slice 8 wrote a project-local pilot at projects/atlas/tickets/ so the new ticket shape
# could be judged while tasks/AIOS-014/ stayed authoritative. By shape alone that is exactly
# a half-done move — real content on the new side of two roots whose old sides are still
# live — so the resolver called `projects` and `tickets` conflicts and doctor, init and
# handoff all refused. A mirror declares itself in its own front matter; the resolver reads
# that declaration instead of guessing.
mk_pilot() {  # <file> — front matter pointing back at the record that still owns this
  printf -- '---\nproject: atlas\nmigrated_from: tasks/AIOS-014/task.md\nrole: pilot mirror\n---\n' > "$1"
}

PP="$TMP/pilot"; ATLAS_HOME="$PP" "$CLI/atlas-init" >/dev/null 2>&1
rm -rf "$PP/projects"
mkdir -p "$PP/user/04-projects"
mkdir -p "$PP/tasks/AIOS-014"
echo "the authoritative record" > "$PP/tasks/AIOS-014/task.md"
echo "the real projects root"   > "$PP/user/04-projects/registry.md"
# What doctor says about this workspace before the pilot exists, so the pilot's own effect
# on it can be isolated from whatever else a bare fixture workspace fails.
doc_before=$(ATLAS_HOME="$PP" "$CLI/atlas-doctor" --quiet 2>&1); doc_rc_before=$?

mkdir -p "$PP/projects/atlas/tickets" "$PP/projects/atlas/context"
mk_pilot "$PP/projects/atlas/index.md"
mk_pilot "$PP/projects/atlas/context/current.md"

[ "$(ATLAS_HOME="$PP" "$PA" layout projects)" = "old" ]
chk "a marked pilot does not make the projects root conflict" $?
[ "$(ATLAS_HOME="$PP" "$PA" layout tickets)" = "old" ]
chk "  ...nor the ticket root" $?
[ "$(ATLAS_HOME="$PP" "$PA" get projects)" = "$PP/user/04-projects" ]
chk "projects still resolves to the root that is still authoritative" $?
[ "$(ATLAS_HOME="$PP" "$PA" get tickets)" = "$PP/tasks" ]
chk "  ...and tickets to tasks/, not to the mirror" $?
ATLAS_HOME="$PP" "$PA" check >/dev/null 2>&1
[ $? -eq 0 ];                            chk "check reports no conflicting root" $?

doc_after=$(ATLAS_HOME="$PP" "$CLI/atlas-doctor" --quiet 2>&1); doc_rc_after=$?
echo "$doc_after" | grep -q "exists in both layouts"
[ $? -ne 0 ];                            chk "doctor no longer fails on the pilot" $?
[ "$doc_rc_after" -eq "$doc_rc_before" ] && [ "$doc_after" = "$doc_before" ]
chk "  ...and the pilot changes nothing else it reports" $?
ATLAS_HOME="$PP" "$CLI/atlas-handoff" list AIOS-014 >/dev/null 2>&1
chk "handoff starts up instead of dying on an unresolvable ticket root" $?

task_before=$(shasum "$PP/tasks/AIOS-014/task.md")
pilot_before=$(shasum "$PP/projects/atlas/index.md" "$PP/projects/atlas/context/current.md")
out=$(ATLAS_HOME="$PP" "$CLI/atlas-init" 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "init runs instead of refusing" $?
echo "$out" | grep -q "REFUSED"
[ $? -ne 0 ];                            chk "  ...without a layout refusal" $?
[ "$task_before" = "$(shasum "$PP/tasks/AIOS-014/task.md")" ] &&
  [ "$pilot_before" = "$(shasum "$PP/projects/atlas/index.md" "$PP/projects/atlas/context/current.md")" ]
chk "  ...without touching the old record or pilot marker" $?
grep -q "the authoritative record" "$PP/tasks/AIOS-014/task.md"
chk "  ...and left the old task record alone" $?

# The exemption is evidence, not a hole. Without the declaration the same tree is a
# half-done move again, and is reported as one.
PU="$TMP/pilot-unmarked"
mkdir -p "$PU/user/04-projects" "$PU/tasks" "$PU/projects/atlas/tickets"
echo "work, with nothing said about where it came from" > "$PU/projects/atlas/index.md"
[ "$(ATLAS_HOME="$PU" "$PA" layout tickets)" = "conflict" ]
chk "an unmarked project-local ticket directory still conflicts" $?
[ "$(ATLAS_HOME="$PU" "$PA" layout projects)" = "conflict" ]
chk "  ...and so does the projects root holding it" $?
# A marker has to point back into the root that has not moved. Anything else is prose.
printf -- '---\nmigrated_from: user/04-projects/atlas\n---\n' > "$PU/projects/atlas/index.md"
[ "$(ATLAS_HOME="$PU" "$PA" layout tickets)" = "conflict" ]
chk "  ...and a migrated_from that names no task record exempts nothing" $?

# A pilot beside a real project is a real projects root: the exemption covers a directory
# that is nothing but pilot, never one that merely contains a pilot.
PM="$TMP/pilot-mixed"
mkdir -p "$PM/user/04-projects" "$PM/tasks" "$PM/projects/atlas/tickets" "$PM/projects/rccm"
mk_pilot "$PM/projects/atlas/index.md"
echo "a real project record" > "$PM/projects/rccm/project.md"
[ "$(ATLAS_HOME="$PM" "$PA" layout projects)" = "conflict" ]
chk "a new projects/ carrying real data still conflicts" $?
[ "$(ATLAS_HOME="$PM" "$PA" layout tickets)" = "old" ]
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
  [ "$(ATLAS_HOME="$PO" "$PA" layout "$r")" = "conflict" ] || n=$((n+1))
done
[ "$n" -eq 0 ];  chk "a marker cannot exempt memory, knowledge, rules or runtime" $?
ATLAS_HOME="$PO" "$PA" check >/dev/null 2>&1
[ $? -eq 4 ];    chk "  ...and all four are still reported" $?

# =====================================================================================
t "private path compatibility: the personal/ retarget"
# The owner renamed the final private root from `user/` to `personal/` before any private
# data moved: `personal/` holds long-lived personal material, `projects/` holds work, and
# `internal/` holds the machinery. Only the new side of the table moved. The old roots are
# still the authoritative ones on this machine, and still what `atlas init` creates, so
# every workspace that has not migrated yet must resolve exactly as it did before.
grep -q '"personal/memory ' "$PA" && grep -q '"personal/knowledge ' "$PA"
chk "the table's new side names personal/memory and personal/knowledge" $?
grep -Eq '"user/(memory|knowledge)[[:space:]]' "$PA"
[ $? -ne 0 ];  chk "  ...and no longer names user/memory or user/knowledge" $?

RT="$TMP/retarget"

# --- memory ---------------------------------------------------------------------------
mkdir -p "$RT/m-old/user/02-personal/memory"
[ "$(ATLAS_HOME="$RT/m-old" "$PA" layout memory)" = "old" ]
chk "the old memory root alone is still layout old" $?
[ "$(ATLAS_HOME="$RT/m-old" "$PA" get memory)" = "$RT/m-old/user/02-personal/memory" ]
chk "  ...resolving to user/02-personal/memory, unchanged by the retarget" $?

mkdir -p "$RT/m-new/personal/memory"
[ "$(ATLAS_HOME="$RT/m-new" "$PA" layout memory)" = "new" ]
chk "personal/memory alone is layout new" $?
[ "$(ATLAS_HOME="$RT/m-new" "$PA" get memory)" = "$RT/m-new/personal/memory" ]
chk "  ...and resolves to personal/memory" $?

# The retarget replaced the new side rather than adding to it: the path this table used to
# call "new" is now an ordinary directory, and must not stand in for the root.
mkdir -p "$RT/m-stale/user/memory"
[ "$(ATLAS_HOME="$RT/m-stale" "$PA" layout memory)" = "none" ]
chk "user/memory is no longer the new side of memory" $?
[ "$(ATLAS_HOME="$RT/m-stale" "$PA" get memory)" = "$RT/m-stale/personal/memory" ]
chk "  ...so the resolver falls back to init's new memory path" $?

mkdir -p "$RT/m-both/user/02-personal/memory" "$RT/m-both/personal/memory"
echo "old store" > "$RT/m-both/user/02-personal/memory/i.md"
echo "new store" > "$RT/m-both/personal/memory/i.md"
[ "$(ATLAS_HOME="$RT/m-both" "$PA" layout memory)" = "conflict" ]
chk "the old memory root beside personal/memory is still a conflict" $?
out=$(ATLAS_HOME="$RT/m-both" "$PA" get memory 2>&1); rc=$?
[ "$rc" -eq 3 ] && echo "$out" | grep -q "$RT/m-both/personal/memory"
chk "  ...refused, naming the new side by its personal/ path" $?
grep -q "old store" "$RT/m-both/user/02-personal/memory/i.md" &&
  grep -q "new store" "$RT/m-both/personal/memory/i.md"
chk "  ...and neither store was touched" $?

# --- knowledge --------------------------------------------------------------------------
mkdir -p "$RT/k-old/user/05-knowledge"
[ "$(ATLAS_HOME="$RT/k-old" "$PA" layout knowledge)" = "old" ]
chk "the old knowledge root alone is still layout old" $?
[ "$(ATLAS_HOME="$RT/k-old" "$PA" get knowledge)" = "$RT/k-old/user/05-knowledge" ]
chk "  ...resolving to user/05-knowledge, unchanged by the retarget" $?

mkdir -p "$RT/k-new/personal/knowledge"
[ "$(ATLAS_HOME="$RT/k-new" "$PA" layout knowledge)" = "new" ]
chk "personal/knowledge alone is layout new" $?
[ "$(ATLAS_HOME="$RT/k-new" "$PA" get knowledge)" = "$RT/k-new/personal/knowledge" ]
chk "  ...and resolves to personal/knowledge" $?

mkdir -p "$RT/k-stale/user/knowledge"
[ "$(ATLAS_HOME="$RT/k-stale" "$PA" layout knowledge)" = "none" ]
chk "user/knowledge is no longer the new side of knowledge" $?
[ "$(ATLAS_HOME="$RT/k-stale" "$PA" get knowledge)" = "$RT/k-stale/personal/knowledge" ]
chk "  ...so the resolver falls back to init's new knowledge path" $?

mkdir -p "$RT/k-both/user/05-knowledge" "$RT/k-both/personal/knowledge"
echo "old store" > "$RT/k-both/user/05-knowledge/i.md"
echo "new store" > "$RT/k-both/personal/knowledge/i.md"
[ "$(ATLAS_HOME="$RT/k-both" "$PA" layout knowledge)" = "conflict" ]
chk "the old knowledge root beside personal/knowledge is still a conflict" $?
out=$(ATLAS_HOME="$RT/k-both" "$PA" get knowledge 2>&1); rc=$?
[ "$rc" -eq 3 ] && echo "$out" | grep -q "$RT/k-both/personal/knowledge"
chk "  ...refused, naming the new side by its personal/ path" $?

# --- the retarget changed the two paths and nothing else ----------------------------------
# The pilot exemption is the one narrow hole in conflict detection, and it stayed exactly
# as narrow: still only `projects` and `tickets`, still nothing under the personal/ roots.
RP="$TMP/retarget-pilot"
mkdir -p "$RP/user/04-projects" "$RP/tasks" "$RP/projects/atlas/tickets"
mk_pilot "$RP/projects/atlas/index.md"
[ "$(ATLAS_HOME="$RP" "$PA" layout tickets)" = "old" ] &&
  [ "$(ATLAS_HOME="$RP" "$PA" layout projects)" = "old" ]
chk "a marked project-local pilot still does not conflict after the retarget" $?
echo "unmarked work" > "$RP/projects/atlas/index.md"
[ "$(ATLAS_HOME="$RP" "$PA" layout tickets)" = "conflict" ] &&
  [ "$(ATLAS_HOME="$RP" "$PA" layout projects)" = "conflict" ]
chk "  ...and an unmarked one still does" $?
mk_pilot "$RP/projects/atlas/index.md"
mkdir -p "$RP/user/02-personal/memory" "$RP/personal/memory"
mk_pilot "$RP/personal/memory/index.md"
[ "$(ATLAS_HOME="$RP" "$PA" layout memory)" = "conflict" ]
chk "a pilot marker under personal/memory exempts nothing" $?

# The other three roots are untouched by this slice.
RO="$TMP/retarget-others"
mkdir -p "$RO/projects" "$RO/internal/governance/rules" "$RO/internal/runtime"
[ "$(ATLAS_HOME="$RO" "$PA" layout projects)" = "new" ] &&
  [ "$(ATLAS_HOME="$RO" "$PA" layout rules)" = "new" ] &&
  [ "$(ATLAS_HOME="$RO" "$PA" layout runtime)" = "new" ]
chk "projects, rules and runtime keep the new sides they already had" $?
# The root list is asserted whole, so a root can never be added by accident — only by
# editing this line. Slice 8b left daily and templates out because nothing resolved them;
# Slice 10A added them, with config, policies, skills, agents and helpers, because those
# are exactly the seven the live CLI tools still named literally. Slice 10B adds schemas
# and professional so init can create the final private layout without spelling the old
# section names downstream. `inbox` came when 00-inbox moved to personal/, because
# atlas-memory quarantines rescued data into it; `sessions` came last, when session
# records moved under internal/ — the owner's recorded reason being that they are Atlas
# operational records, not daily-use personal material. See cli/atlas-paths.
roots=$(. "$PA"; printf '%s' "$ATLAS_PATH_ROOTS")
[ "$roots" = "memory knowledge projects tickets rules runtime config policies daily templates skills agents helpers schemas professional inbox sessions" ]
chk "the resolver root list is exactly the seventeen declared roots" $?
case " $roots " in *" schemas "*) true ;; *) false ;; esac
chk "  ...including schemas" $?
case " $roots " in *" professional "*) true ;; *) false ;; esac
chk "  ...including professional" $?

# =====================================================================================
t "private path compatibility: inbox and the handoff template"
# The last two sections Slice 9 was not asked to move. `inbox` earns a resolver root
# because `atlas-memory` quarantines rescued data into it; the handoff template does not,
# because nothing reads it — `atlas-handoff` names it in prose for a human and never opens
# it, and a root with no caller would widen conflict detection for nobody.
IB="$TMP/inbox-root"; ATLAS_HOME="$IB" "$CLI/atlas-init" >/dev/null 2>&1
[ "$(ATLAS_HOME="$IB" "$PA" get inbox)" = "$IB/personal/inbox" ]
chk "init seeds inbox at its new address" $?
[ "$(ATLAS_HOME="$IB" "$PA" layout inbox)" = "new" ]
chk "  ...and the resolver reports it as the new layout" $?
IO="$TMP/inbox-old"; mkdir -p "$IO/user/00-inbox"
[ "$(ATLAS_HOME="$IO" "$PA" get inbox)" = "$IO/user/00-inbox" ]
chk "an old-layout workspace still resolves inbox to user/00-inbox" $?
mkdir -p "$IO/personal/inbox"
[ "$(ATLAS_HOME="$IO" "$PA" layout inbox)" = "conflict" ]
chk "  ...and both at once is a conflict, not a merge" $?
grep -q 'private_path_or_die("inbox")' "$CLI/atlas-memory"
chk "memory quarantines through the resolver, not a literal path" $?
grep -Eq 'ATLAS_HOME[^\n]*(user|00-inbox)' "$CLI/atlas-memory"
[ $? -ne 0 ];                            chk "  ...and names no old inbox path at all" $?
# Atlas-canonical (T-020 family): resolved from ATLAS_HOME directly, no internal/
# prefix — templates/ lives at the workspace top level, not under internal/.
grep -q 'TEMPLATE_REF = str(ATLAS_HOME / "templates" / "agent-handoff.md")' "$CLI/atlas-handoff"
chk "the handoff template reference names its real location" $?
python3 - "$CLI/atlas-handoff" <<'PYEOF'
import ast, pathlib, sys
# TEMPLATE_REF must stay a bare string: the moment something opens it, it needs a root.
src = pathlib.Path(sys.argv[1]).read_text()
tree = ast.parse(src)
used = [n for n in ast.walk(tree)
        if isinstance(n, ast.Name) and n.id == "TEMPLATE_REF"
        and not isinstance(getattr(n, "ctx", None), ast.Store)]
sys.exit(1 if any(
    isinstance(p, ast.Call) and any(u is a for a in getattr(p, "args", []))
    for p in ast.walk(tree) for u in used
    if isinstance(p, ast.Call) and isinstance(p.func, ast.Attribute)
    and p.func.attr in {"open", "read_text", "read_bytes"}) else 0)
PYEOF
chk "  ...and is never opened, so it needs no resolver root" $?

# =====================================================================================
t "private path compatibility: an archived pointer layer is not a live root"
# Slice 9 is the mirror image of the pilot. Once every tasks/<ID>/ record has moved into
# per-project tickets, what is left behind is a compatibility layer of pointers — and by
# shape alone that is again a half-done move: real content on the new side of `tickets`
# while the old side still exists. So the archive declares itself the same way the pilot did, in the two
# lines the pointer template writes, and the resolver reads the declaration rather than
# guessing. The test is "does any authoritative record still live here?", not "is every
# directory a pointer".
mk_ptr() {   # <dir> <moved-to> — a pointer that renounces authority and names its successor
  mkdir -p "$1"
  printf -- '---\nid: X\nstate: done\nproject: p\nmoved_to: %s\nauthoritative: false\n---\n' "$2" > "$1/task.md"
  printf -- 'moved_to: %s\nstatus: archived-pointer\nauthoritative: false\n' "$2" > "$1/README.md"
}
mk_item() {  # <dir> — a real, authoritative ticket record
  mkdir -p "$1"; printf -- '---\nid: X\nstate: active\nproject: p\n---\n' > "$1/task.md"
}

AR="$TMP/archived"; ATLAS_HOME="$AR" "$CLI/atlas-init" >/dev/null 2>&1
# A workspace that has finished the projects move, so the only root still under test is
# `tickets`. Leaving user/04-projects/ behind would be a second half-done move and would make
# `projects` conflict for reasons that have nothing to do with the archive layer.
rm -rf "$AR/user/04-projects"
mk_item "$AR/projects/atlas/tickets/AIOS-014"
mk_ptr  "$AR/tasks/AIOS-014" "projects/atlas/tickets/AIOS-014/task.md"
mkdir -p "$AR/tasks/archive"                       # holds no record at all
printf 'a pointer index\n' > "$AR/tasks/index.md"  # a file, not a record

[ "$(ATLAS_HOME="$AR" "$PA" layout tickets)" = "new" ]
chk "a fully archived tasks/ no longer holds the ticket root" $?
ATLAS_HOME="$AR" "$PA" check >/dev/null 2>&1
[ $? -eq 0 ];                            chk "  ...so check reports no conflicting root" $?
ATLAS_HOME="$AR" "$PA" get tickets >/dev/null 2>&1
[ $? -eq 4 ];                            chk "  ...and tickets still refuses to name one root" $?
[ -f "$AR/tasks/AIOS-014/task.md" ] && [ -d "$AR/tasks/archive" ]
chk "  ...having deleted nothing it read" $?

# One record that has not renounced authority is enough to make the old side live again.
mk_item "$AR/tasks/AIOS-012"
[ "$(ATLAS_HOME="$AR" "$PA" layout tickets)" = "conflict" ]
chk "one unarchived record makes tasks/ a live root, and a conflict" $?
ATLAS_HOME="$AR" "$PA" check >/dev/null 2>&1
[ $? -ne 0 ];                            chk "  ...which check reports" $?
rm -rf "$AR/tasks/AIOS-012"

# Half a declaration is not a declaration: a pointer must both renounce authority and say
# where the record went, or it is still a record.
mkdir -p "$AR/tasks/AIOS-013"
printf -- '---\nid: X\nauthoritative: false\n---\n' > "$AR/tasks/AIOS-013/task.md"
[ "$(ATLAS_HOME="$AR" "$PA" layout tickets)" = "conflict" ]
chk "authoritative: false without moved_to is not a pointer" $?
printf -- '---\nid: X\nmoved_to: projects/atlas/tickets/AIOS-013/task.md\n---\n' > "$AR/tasks/AIOS-013/task.md"
[ "$(ATLAS_HOME="$AR" "$PA" layout tickets)" = "conflict" ]
chk "  ...and moved_to without authoritative: false is not either" $?
rm -rf "$AR/tasks/AIOS-013"

# Scoped to `tickets` alone, exactly as the pilot marker is scoped to `projects` and `tickets`.
AS="$TMP/archived-scope"; ATLAS_HOME="$AS" "$CLI/atlas-init" >/dev/null 2>&1
mkdir -p "$AS/personal/memory"; mk_ptr "$AS/user/02-personal/memory/whatever" "elsewhere/task.md"
[ "$(ATLAS_HOME="$AS" "$PA" layout memory)" = "conflict" ]
chk "a pointer under memory exempts nothing" $?
mkdir -p "$AS/internal/governance/rules"; mk_ptr "$AS/system/rules/whatever" "elsewhere/task.md"
[ "$(ATLAS_HOME="$AS" "$PA" layout rules)" = "conflict" ]
chk "  ...and one under rules exempts nothing" $?

# =====================================================================================
t "private path compatibility: one ticket, by id"
# `tickets` has no single root once records live per project, so the useful question is not
# "where is the ticket root" but "where is this ticket". The lookup prefers the authoritative
# record, falls back to a record still sitting in the old layout, and otherwise follows the
# pointer the archive layer leaves behind. It never merges and never picks between two.
[ "$(ATLAS_HOME="$AR" "$PA" ticket AIOS-014)" = "$AR/projects/atlas/tickets/AIOS-014" ]
chk "an id resolves to its authoritative ticket" $?

# A record the glob cannot see is still reachable, because the pointer names where it went.
mkdir -p "$AR/elsewhere/AIOS-020"; printf -- '---\nid: X\n---\n' > "$AR/elsewhere/AIOS-020/task.md"
mk_ptr "$AR/tasks/AIOS-020" "elsewhere/AIOS-020/task.md"
[ "$(ATLAS_HOME="$AR" "$PA" ticket AIOS-020)" = "$AR/elsewhere/AIOS-020" ]
chk "  ...or through the pointer, when it moved somewhere the glob does not cover" $?

# A record still living in the old layout answers for itself.
mk_item "$AR/tasks/AIOS-021"
[ "$(ATLAS_HOME="$AR" "$PA" ticket AIOS-021)" = "$AR/tasks/AIOS-021" ]
chk "  ...and a record still in tasks/ answers for itself" $?
rm -rf "$AR/tasks/AIOS-021"

ATLAS_HOME="$AR" "$PA" ticket AIOS-999 >/dev/null 2>&1
[ $? -eq 4 ];                            chk "an id that exists nowhere is not found, not guessed" $?
ATLAS_HOME="$AR" "$PA" ticket 'a/b' >/dev/null 2>&1
[ $? -eq 2 ];                            chk "an id with a path separator is refused" $?
ATLAS_HOME="$AR" "$PA" ticket '' >/dev/null 2>&1
[ $? -eq 2 ];                            chk "  ...and so is an empty one" $?

# Two projects claiming one id is a fact about the workspace, not a choice for the resolver.
mk_item "$AR/projects/other/tickets/AIOS-014"
out=$(ATLAS_HOME="$AR" "$PA" ticket AIOS-014 2>&1); rc=$?
[ "$rc" -eq 3 ];                         chk "one id under two projects is a conflict" $?
echo "$out" | grep -q "more than one project"
chk "  ...named in the report, with both paths" $?
[ -d "$AR/projects/atlas/tickets/AIOS-014" ] && [ -d "$AR/projects/other/tickets/AIOS-014" ]
chk "  ...and neither side was touched" $?
rm -rf "$AR/projects/other"

# =====================================================================================
t "contraction: the seven shimmed roots resolve like every other root"
# Slice 9 moved the private roots but left seven behind as symlink shims, because the CLI
# tools named them literally: system/config, system/policies, user/01-daily,
# user/06-templates, skills, agents and scripts. Slice 10A gave each one a resolver root,
# which is what makes removing those shims possible later. Same four states as the
# original six roots — old, new, neither, conflict — and the same refusal.
SEVEN="config:internal/config:system/config
policies:internal/governance/policies:system/policies
daily:personal/daily:user/01-daily
templates:personal/templates:user/06-templates
skills:internal/extensions/skills:skills
agents:internal/extensions/agents:agents
helpers:internal/helpers:scripts"

C_OLD="$TMP/c-old"; C_NEW="$TMP/c-new"; C_NONE="$TMP/c-none"; C_SHIM="$TMP/c-shim"
mkdir -p "$C_OLD" "$C_NEW" "$C_NONE" "$C_SHIM"
bad_old=0; bad_new=0; bad_none=0; bad_shim=0; bad_pair=0
while IFS=: read -r root new old; do
  [ -n "$root" ] || continue
  # Each root's own pair, read back from the resolver rather than restated here.
  pair=$(. "$PA"; _atlas_pair "$root")
  [ "${pair%% *}" = "$new" ] && [ "${pair##* }" = "$old" ] || bad_pair=1

  mkdir -p "$C_OLD/$old"
  [ "$(ATLAS_HOME="$C_OLD" "$PA" layout "$root")" = "old" ] &&
    [ "$(ATLAS_HOME="$C_OLD" "$PA" get "$root")" = "$C_OLD/$old" ] || bad_old=1

  mkdir -p "$C_NEW/$new"
  [ "$(ATLAS_HOME="$C_NEW" "$PA" layout "$root")" = "new" ] &&
    [ "$(ATLAS_HOME="$C_NEW" "$PA" get "$root")" = "$C_NEW/$new" ] || bad_new=1

  # Nothing there yet resolves to the new path on purpose: that is now the layout
  # `atlas init` creates, and a fresh workspace must not grow the shim layer back.
  [ "$(ATLAS_HOME="$C_NONE" "$PA" layout "$root")" = "none" ] &&
    [ "$(ATLAS_HOME="$C_NONE" "$PA" get "$root")" = "$C_NONE/$new" ] || bad_none=1

  # The live state of a migrated workspace: the real directory at the new name, the old
  # name still reaching it through a symlink. One directory, two names — compatibility,
  # not a clash.
  mkdir -p "$C_SHIM/$new" "$C_SHIM/$(dirname "$old")"
  ln -s "$C_SHIM/$new" "$C_SHIM/$old"
  [ "$(ATLAS_HOME="$C_SHIM" "$PA" layout "$root")" = "new" ] &&
    [ "$(ATLAS_HOME="$C_SHIM" "$PA" get "$root")" = "$C_SHIM/$new" ] || bad_shim=1
done <<< "$SEVEN"
[ "$bad_pair" -eq 0 ];  chk "each new root declares the move Slice 9 actually made" $?
[ "$bad_old" -eq 0 ];   chk "old path only -> the old path, for all seven" $?
[ "$bad_new" -eq 0 ];   chk "new path only -> the new path, for all seven" $?
[ "$bad_none" -eq 0 ];  chk "neither -> the new layout init now creates, for all seven" $?
[ "$bad_shim" -eq 0 ];  chk "a symlink shim resolves to the new path, for all seven" $?
ATLAS_HOME="$C_SHIM" "$PA" check >/dev/null 2>&1
[ $? -eq 0 ];           chk "  ...and a fully shimmed workspace reports no conflict" $?

# Two real directories is still a conflict, refused the same way.
C_BOTH="$TMP/c-both"; mkdir -p "$C_BOTH/internal/config" "$C_BOTH/system/config"
echo "new side" > "$C_BOTH/internal/config/settings.yaml"
echo "old side" > "$C_BOTH/system/config/settings.yaml"
[ "$(ATLAS_HOME="$C_BOTH" "$PA" layout config)" = "conflict" ]
chk "config in both layouts, as two directories -> conflict" $?
out=$(ATLAS_HOME="$C_BOTH" "$PA" get config 2>&1); rc=$?
[ "$rc" -eq 3 ] && echo "$out" | grep -qi "will not merge"
chk "  ...refused, and it will not merge them" $?
grep -q "new side" "$C_BOTH/internal/config/settings.yaml" &&
  grep -q "old side" "$C_BOTH/system/config/settings.yaml"
chk "  ...neither side was touched" $?

# =====================================================================================
t "contraction: the tools that named those paths literally now ask"
# The point of the slice. Each of these used to build a path out of \$ATLAS_HOME and a
# literal old directory name; a workspace that had moved was reached only through the
# shim. Asserted at the source, because that is the property that lets the shim go.
grep -q 'private_path_or_die("config") / "authority.yaml"' "$CLI/atlas-capability"
chk "atlas-capability reads the grant ledger through the resolver" $?
grep -q 'private_path_or_die("config") / "profile.yaml"' "$CLI/atlas-render"
chk "atlas-render reads the profile through the resolver" $?
grep -q 'private_path_or_die("policies") / "privacy-terms.txt"' "$CLI/atlas-privacy-scan"
chk "atlas-privacy-scan reads the user's terms through the resolver" $?
grep -q 'atlas-paths" get config' "$CLI/atlas-onboard"
chk "atlas-onboard reads its state marker through the resolver" $?
# An old path is still allowed as the DEFAULT of a resolved variable — ${ATLAS_PATH_X:-…}
# is how a fresh workspace keeps working when the resolver has no single answer. What must
# be gone is the bare literal: a path built out of $ATLAS_HOME and a directory name that
# has moved. So the fallback forms are stripped out first, and whatever remains is a
# consumer that never asked.
still_literal=""
for lit in 'ATLAS_HOME/system/config' 'ATLAS_HOME/system/policies' \
           'ATLAS_HOME/user/01-daily' 'ATLAS_HOME/user/06-templates' \
           'ATLAS_HOME/skills' 'ATLAS_HOME/agents' 'ATLAS_HOME/scripts'; do
  for f in "$CLI/atlas-status" "$CLI/atlas-onboard" "$CLI/atlas-render" \
           "$CLI/atlas-privacy-scan" "$CLI/atlas-capability"; do
    sed 's/\${[A-Za-z_][A-Za-z0-9_]*:-[^}]*}//g' "$f" | grep -qF "\$$lit" \
      && still_literal="$still_literal $(basename "$f"):$lit"
  done
done
[ -z "$still_literal" ] || printf '        still literal:%s\n' "$still_literal"
[ -z "$still_literal" ]
chk "no live consumer still builds one of the seven paths by hand" $?
# atlas-doctor and atlas-init may still mention the old names on purpose, in the places
# that describe the old side of a move rather than reaching live data.
grep -q 'ATLAS_PATH_CONFIG:-\$ATLAS_HOME/internal/config' "$CLI/atlas-doctor"
chk "doctor falls back to the new config path when the resolver has no answer" $?
grep -q 'for r in memory knowledge projects rules runtime config policies daily templates skills agents helpers schemas professional' "$CLI/atlas-doctor"
chk "  ...and checks all of them through the resolver's layout answer" $?

# atlas-hook is the one file that may not ask: the resolver lives in the repository, and
# the hook runs before the repository has been found. So it checks both, newest first.
H_NEW="$TMP/hook-new"; mkdir -p "$H_NEW/internal/config"
printf 'atlas_repo: %s\n' "$REPO" > "$H_NEW/internal/config/settings.yaml"
ATLAS_HOME="$H_NEW" "$CLI/atlas-hook" cli/atlas-paths list >/dev/null 2>&1
chk "the hook finds the repository through the new config path" $?
H_OLD="$TMP/hook-old"; mkdir -p "$H_OLD/system/config"
printf 'atlas_repo: %s\n' "$REPO" > "$H_OLD/system/config/settings.yaml"
ATLAS_HOME="$H_OLD" "$CLI/atlas-hook" cli/atlas-paths list >/dev/null 2>&1
chk "  ...and still through the old one" $?
H_BOTH="$TMP/hook-both"; mkdir -p "$H_BOTH/internal/config" "$H_BOTH/system/config"
printf 'atlas_repo: %s\n' "$REPO"        > "$H_BOTH/internal/config/settings.yaml"
printf 'atlas_repo: %s\n' "/nonexistent" > "$H_BOTH/system/config/settings.yaml"
ATLAS_HOME="$H_BOTH" "$CLI/atlas-hook" cli/atlas-paths list >/dev/null 2>&1
chk "  ...and prefers the new one when both exist" $?
# T-046: atlas-hook's resolution has a third fallback — ${ATLAS_HOME:-$HOME/atlas}/config
# /settings.yaml — checked when neither ATLAS_HOME-relative path has a config. Left
# unset, that falls through to the real ~/atlas on the machine running this suite,
# which has a real settings.yaml and masks the "neither exists" failure this asserts.
# ATLAS_HOME must be isolated here too, not just ATLAS_HOME.
out=$(ATLAS_HOME="$TMP/hook-none" ATLAS_HOME="$TMP/hook-none-atlas" \
      "$CLI/atlas-hook" cli/atlas-paths list 2>&1); rc=$?
[ "$rc" -eq 78 ] && echo "$out" | grep -q "internal/config/settings.yaml" \
                 && echo "$out" | grep -q "system/config/settings.yaml"
chk "  ...and names both when it finds neither" $?

# A workspace that has fully moved must not be told its sections are missing — that
# report is what the shims were propping up.
D_NEW="$TMP/doctor-new"
mkdir -p "$D_NEW/personal/memory" "$D_NEW/personal/knowledge" "$D_NEW/projects" \
         "$D_NEW/personal/professional" "$D_NEW/personal/daily" "$D_NEW/personal/templates" \
         "$D_NEW/internal/sessions" "$D_NEW/internal/schemas" "$D_NEW/internal/runtime" \
         "$D_NEW/internal/config" "$D_NEW/internal/governance/rules" \
         "$D_NEW/internal/governance/policies" "$D_NEW/internal/extensions/skills" \
         "$D_NEW/internal/extensions/agents" "$D_NEW/internal/helpers" \
         "$D_NEW/personal/inbox"
dout=$(ATLAS_HOME="$D_NEW" "$CLI/atlas-doctor" --quiet 2>&1)
printf '%s' "$dout" | grep -q "missing section"
[ $? -ne 0 ];           chk "doctor reports no missing section on a fully moved workspace" $?
printf '%s' "$dout" | grep -qE 'exists in both layouts'
[ $? -ne 0 ];           chk "  ...and no root conflict either" $?

# =====================================================================================
t "private path compatibility: rewrite maps an old-layout path onto the live one"
[ "$("$PA" rewrite user/05-knowledge/README.md)" = "$PW/user/05-knowledge/README.md" ]
chk "a path under an unmoved root is unchanged" $?
[ "$("$PA" rewrite user/02-personal/memory/MEMORY.md)" = "$PW/personal/memory/MEMORY.md" ]
chk "a path under a moved root is rewritten onto the new one" $?
WR_OLD="$TMP/rewrite-old"; mkdir -p "$WR_OLD/system/config"
[ "$(ATLAS_HOME="$WR_OLD" "$PA" rewrite internal/config/settings.yaml)" = "$WR_OLD/system/config/settings.yaml" ]
chk "a new-layout template path is rewritten onto an old workspace" $?
[ "$("$PA" rewrite build-out/artifact.json)" = "$PW/build-out/artifact.json" ]
chk "a path under no moving root is left alone" $?
# sessions used to be that example. It became a root when session records moved under
# internal/, so the same call now has to come back rewritten rather than untouched.
[ "$("$PA" rewrite sessions/2026/x.md)" = "$PW/internal/sessions/2026/x.md" ]
chk "  ...and a path under sessions is rewritten now that it is one" $?
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
py=$(cd "$REPO" && ATLAS_HOME="$PW" python3 -c "
import sys; sys.path.insert(0, 'cli')
from atlas_paths import private_path, private_layout, PathConflict
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
IW="$TMP/init-layout"
mkdir -p "$IW/user/02-personal/memory"
echo "old seed" > "$IW/user/02-personal/memory/MEMORY.md"
ATLAS_HOME="$IW" "$CLI/atlas-init" >/dev/null 2>&1
mkdir -p "$IW/personal/memory" && mv "$IW/user/02-personal/memory/MEMORY.md" "$IW/personal/memory/"
rm -rf "$IW/user/02-personal"
ATLAS_HOME="$IW" "$CLI/atlas-init" >/dev/null 2>&1
[ ! -d "$IW/user/02-personal" ];         chk "init does not re-create a root that has moved" $?
[ ! -e "$IW/user/02-personal/memory/MEMORY.md" ] && [ -f "$IW/personal/memory/MEMORY.md" ]
chk "  ...and re-seeds into the store that exists, not beside it" $?

mkdir -p "$IW/user/02-personal/memory"; echo "a second store" > "$IW/user/02-personal/memory/x.md"
out=$(ATLAS_HOME="$IW" "$CLI/atlas-init" 2>&1); rc=$?
[ "$rc" -ne 0 ];                         chk "init refuses outright when a root exists in both layouts" $?
echo "$out" | grep -q "REFUSED";         chk "  ...and says so" $?
grep -q "a second store" "$IW/user/02-personal/memory/x.md" && [ -f "$IW/personal/memory/MEMORY.md" ]
chk "  ...having touched neither side" $?

out=$(ATLAS_HOME="$IW" "$CLI/atlas-doctor" 2>&1); rc=$?
echo "$out" | grep -q "exists in both layouts"; chk "doctor reports the same conflict as a failure" $?
[ "$rc" -gt 0 ];                                chk "  ...and exits non-zero" $?

# =====================================================================================
t "private path compatibility: a workspace path containing spaces"
# Regression. The resolver's answers used to reach the shell as text and be re-parsed
# with eval, so "/my ai os/user/..." became the command `ai` with an argument: every tool
# still exited 0 while printing "ai: command not found" and silently reporting no paths
# at all. The values are assigned now, never parsed — see atlas_paths_export.
SPW="$TMP/with space/my ai os"; mkdir -p "$SPW"
ATLAS_HOME="$SPW" "$CLI/atlas-init" >/dev/null 2>"$TMP/sp-init.err"
chk "init succeeds under a path with spaces" $?
sp_out=$(ATLAS_HOME="$SPW" "$CLI/atlas" status 2>"$TMP/sp-status.err")
chk "atlas status succeeds" $?
ATLAS_HOME="$SPW" "$CLI/atlas" doctor --quiet >/dev/null 2>"$TMP/sp-doctor.err"
chk "atlas doctor --quiet succeeds" $?

cat "$TMP/sp-init.err" "$TMP/sp-status.err" "$TMP/sp-doctor.err" | grep -q "command not found"
[ $? -ne 0 ];                         chk "no fragment of the path was run as a command" $?
[ ! -s "$TMP/sp-init.err" ] && [ ! -s "$TMP/sp-status.err" ] && [ ! -s "$TMP/sp-doctor.err" ]
chk "  ...and none of the three wrote anything to stderr" $?

# Exiting 0 while reporting nothing was the actual damage, so assert the counts landed.
echo "$sp_out" | grep -Eq 'memory +[0-9]+ files';   chk "status counts the memory store" $?
echo "$sp_out" | grep -Eq 'knowledge +[0-9]+ files'; chk "  ...and knowledge" $?
echo "$sp_out" | grep -q "missing"
[ $? -ne 0 ];                         chk "  ...and reports no root as missing" $?

[ "$(ATLAS_HOME="$SPW" "$PA" layout memory)" = "new" ]
chk "the resolver reports the new layout for a fresh workspace" $?
[ "$(ATLAS_HOME="$SPW" "$PA" get memory)" = "$SPW/personal/memory" ]
chk "  ...and returns the path with its spaces intact" $?

# `env` stays raw so a machine parser gets the literal path; `env --sh` is the form that
# survives eval. Quoting one would have broken the other — hence two.
# Captured, not piped: the suite runs with pipefail and `grep -q` closes the pipe on the
# first match, so a piped resolver would be killed by SIGPIPE and read as a failure.
raw_env=$(ATLAS_HOME="$SPW" "$PA" env)
case "$raw_env" in
  *"ATLAS_PATH_MEMORY=$SPW/personal/memory"*) true ;;
  *) false ;;
esac
chk "env keeps values raw for machine parsers" $?
sh_path=$(eval "$(ATLAS_HOME="$SPW" "$PA" env --sh)"; printf '%s' "$ATLAS_PATH_MEMORY")
[ "$sh_path" = "$SPW/personal/memory" ]
chk "env --sh survives eval with the spaces intact" $?

# The Python adapter reads the raw form; a shell-quoted one would have handed it a path
# with backslashes in it that exists nowhere.
pysp=$(cd "$REPO" && ATLAS_HOME="$SPW" python3 -c "
import sys; sys.path.insert(0, 'cli')
from atlas_paths import private_path
p = private_path('memory')
print('yes' if p.is_dir() else 'no')
")
[ "$pysp" = "yes" ];                  chk "Python resolves a spaced path to a real directory" $?

export ATLAS_HOME="$TMP/clean"

# =====================================================================================
t "atlas usage --guard — warns from measured data, blocks nothing"
GTX="$TMP/guard-transcripts"; mkdir -p "${GTX}/p"
gu() { printf '{"input_tokens":0,"cache_read_input_tokens":%s,"cache_creation_input_tokens":10,"cache_creation":{"ephemeral_5m_input_tokens":10,"ephemeral_1h_input_tokens":0},"output_tokens":5,"output_tokens_details":{"thinking_tokens":1}}' "$1"; }
# A long session whose per-turn context grows far past where it started and never falls.
{ i=1; while [ $i -le 70 ]; do
    printf '{"type":"assistant","sessionId":"BIG","timestamp":"2026-09-01T00:00:00Z","message":{"id":"b%s","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$i" "$(gu $((10000 + i * 6000)))"
    i=$((i+1)); done; } > "${GTX}/p/BIG.jsonl"
# A short, flat one: nothing to say about it.
{ i=1; while [ $i -le 5 ]; do
    printf '{"type":"assistant","sessionId":"SML","timestamp":"2026-09-01T00:00:00Z","message":{"id":"s%s","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$i" "$(gu 12000)"
    i=$((i+1)); done; } > "${GTX}/p/SML.jsonl"

out=$("$CLI/atlas-usage" --transcripts "${GTX}" --guard 2>&1); rc=$?
chk "exits 0 — a warning is not a failure" $rc
printf '%s' "$out" | grep -q 'BIG\|never fell'
chk "flags a long session whose context grew and never fell" $?
printf '%s' "$out" | grep -q 'blocked'
chk "  ...and says plainly that nothing was blocked" $?
"$CLI/atlas-usage" --transcripts "${GTX}" --json 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);sys.exit(0 if d['guard'] else 1)"
chk "the findings are in the machine-readable output too" $?
# The thresholds are relative to the cohort, so a healthy cohort produces nothing.
GTH="$TMP/healthy"; mkdir -p "${GTH}/p"
{ i=1; while [ $i -le 8 ]; do
    printf '{"type":"assistant","sessionId":"OK%s","timestamp":"2026-09-01T00:00:00Z","message":{"id":"o%s","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$i" "$i" "$(gu 12000)"
    i=$((i+1)); done; } > "${GTH}/p/OK.jsonl"
out=$("$CLI/atlas-usage" --transcripts "${GTH}" --guard 2>&1)
printf '%s' "$out" | grep -q 'nothing anomalous'
chk "a cohort with no outlier produces no findings" $?

# =====================================================================================
t "atlas policy — the bootstrap routes, the modules load on demand"
PL="$TMP/pol"; export ATLAS_HOME="$PL"
"$CLI/atlas-init" >/dev/null 2>&1
PRULES="$PL/internal/governance/rules"; PPOL="$PL/internal/governance/policies"
mkdir -p "${PRULES}" "${PPOL}"
cat > "${PRULES}/core.md" <<'EOC'
# Global rules
| Load | When |
|---|---|
| `task` | starting a unit of work |
| `context` | deciding what to read |
EOC
{ printf '# Policy — task\n\nbody-of-task\n'; i=0
  while [ $i -lt 60 ]; do echo "a line of task policy that a bootstrap should not carry"; i=$((i+1)); done
} > "${PPOL}/task.md"
{ printf '# Policy — context\n\nbody-of-context\n'; i=0
  while [ $i -lt 60 ]; do echo "a line of context policy that a bootstrap should not carry"; i=$((i+1)); done
} > "${PPOL}/context.md"

out=$("$CLI/atlas-policy" list 2>&1); rc=$?
chk "list exits 0" $rc
printf '%s' "$out" | grep -q 'task' && printf '%s' "$out" | grep -q 'context'
chk "  ...and names every module on disk" $?
printf '%s' "$out" | grep -q 'body-of-task'
[ $? -ne 0 ];                            chk "  ...without printing any module's body" $?

# No pipe: the module body is long and the match is at the top, so `grep -q` would close
# the pipe first and printf would die of SIGPIPE — which pipefail reports as a failure.
out=$("$CLI/atlas-policy" task 2>&1)
case "$out" in *body-of-task*) true ;; *) false ;; esac
chk "a named module is printed in full" $?
"$CLI/atlas-policy" nonexistent >/dev/null 2>&1
[ $? -ne 0 ];                            chk "an unknown module is refused, not guessed at" $?

"$CLI/atlas-policy" doctor >/dev/null 2>&1
chk "doctor is clean when the table and the modules agree" $?
# A name the bootstrap routes to but which has no file sends a reader nowhere.
printf '| `memory` | recording a fact |\n' >> "${PRULES}/core.md"
out=$("$CLI/atlas-policy" doctor 2>&1)
printf '%s' "$out" | grep -q "routes to 'memory'"
chk "doctor catches a routed module that does not exist" $?
printf '# Policy — memory\n\nbody\n' > "${PPOL}/memory.md"
"$CLI/atlas-policy" doctor >/dev/null 2>&1
chk "  ...and is clean once it does" $?
# A module nothing routes to is unreachable, which is the same as absent.
printf '# Policy — graph\n\nbody\n' > "${PPOL}/graph.md"
out=$("$CLI/atlas-policy" doctor 2>&1)
printf '%s' "$out" | grep -q "routes nothing to it"
chk "doctor catches a module the bootstrap never routes to" $?
rm -f "${PPOL}/graph.md"

# The point of the split: the always-loaded half must be much smaller than the rest.
core_b=$(wc -c < "${PRULES}/core.md"); mod_b=$(cat "${PPOL}"/*.md | wc -c)
[ "$core_b" -lt "$mod_b" ];              chk "the bootstrap is smaller than what it routes to" $?
"$CLI/atlas" policy list >/dev/null 2>&1
chk "reachable as the 'atlas policy' subcommand" $?

# =====================================================================================
t "the real bootstrap stays a bootstrap"
unset ATLAS_HOME
REAL_CORE="$HOME/atlas/internal/governance/rules/core.md"
if [ -f "$REAL_CORE" ]; then
  # A soft budget, asserted loudly: this file is rendered into every client's system
  # prompt, so growth here is charged to every request of every session. It was 24,523
  # bytes before the split. The check is not a cap on content — it is a tripwire for the
  # split quietly being undone.
  b=$(wc -c < "$REAL_CORE")
  [ "$b" -lt 12000 ];                    chk "core.md is still a bootstrap, not a manual ($b bytes)" $?
  grep -q 'atlas policy' "$REAL_CORE";   chk "  ...and it says how to reach the modules" $?
  grep -q 'requires explicit approval, every time' "$REAL_CORE"
  chk "  ...and still carries the remote-git boundary itself" $?
  grep -qi 'never write a secret' "$REAL_CORE"
  chk "  ...and the secrets invariant" $?
  grep -q 'blockquote' "$REAL_CORE"
  chk "  ...and the direction rules a reply would be corrupted without" $?
else
  printf '  %sSKIP%s no private workspace on this machine\n' "$D" "$X"
fi

# =====================================================================================
t "atlas observe — the raw output is kept, only the deciding part is returned"
OB="$TMP/obs-home"; export ATLAS_HOME="$OB"
"$CLI/atlas-init" >/dev/null 2>&1
NOISE="$TMP/noise.sh"
cat > "$NOISE" <<'EOS'
#!/bin/sh
i=0; while [ $i -lt 400 ]; do echo "  PASS step $i completed with no failure at all"; i=$((i+1)); done
echo "  FAIL the thing that actually broke"
echo "src/broken.py:41: error: something specific"
echo "3 passed, 1 failed"
exit 7
EOS
chmod +x "$NOISE"

out=$("$CLI/atlas-observe" -- echo hello 2>&1); rc=$?
chk "a small command exits with the command's own status" $rc
printf '%s' "$out" | grep -q 'hello'
chk "  ...and its output is returned in full, unreduced" $?

out=$("$CLI/atlas-observe" -- "$NOISE" 2>&1); rc=$?
[ "$rc" -eq 7 ];                         chk "the wrapped command's exit code is propagated" $?
printf '%s' "$out" | grep -q '3 passed, 1 failed'
chk "the run's own summary line is returned" $?
printf '%s' "$out" | grep -q 'the thing that actually broke'
chk "the failing line is returned" $?
printf '%s' "$out" | grep -q 'src/broken.py'
chk "the path named by the failure is returned" $?
printf '%s' "$out" | grep -q 'PASS step 12 '
[ $? -ne 0 ];                            chk "the 400 passing lines are NOT admitted" $?
# The guard against the opposite mistake: a PASSING line that contains the word "failure"
# must not be reported as a failure. Getting this wrong fills the observation with noise
# that looks exactly like the signal.
printf '%s' "$out" | grep -q '\[failure\].*PASS step'
[ $? -ne 0 ];                            chk "a passing line mentioning 'failure' is not a signal" $?
[ "${#out}" -lt 4000 ];                  chk "the observation is far smaller than the raw output" $?

OID=$(printf '%s' "$out" | sed -n 's/^observe \([0-9a-z-]*\) .*/\1/p' | head -1)
[ -n "$OID" ];                           chk "the observation reports an id for retrieval" $?
raw=$("$CLI/atlas-observe" show "$OID" --all 2>&1)
printf '%s' "$raw" | grep -q 'PASS step 399'
chk "show --all returns the complete raw output that was withheld" $?
g=$("$CLI/atlas-observe" show "$OID" --grep 'actually broke' 2>&1)
printf '%s' "$g" | grep -q 'actually broke'
chk "show --grep returns a matching slice with line numbers" $?
l=$("$CLI/atlas-observe" show "$OID" --lines 1-2 2>&1)
printf '%s' "$l" | grep -q 'PASS step 0'
chk "show --lines returns the requested range" $?
[ -f "$OB/runtime/observations/$OID/raw.txt" ]
chk "the raw capture lives in runtime state, not beside a task record" $?

# Repeated identical observations: reported, not re-admitted.
again=$("$CLI/atlas-observe" -- "$NOISE" 2>&1)
printf '%s' "$again" | grep -q 'unchanged since'
chk "re-running a command with byte-identical output says so instead of repeating it" $?
printf '%s' "$again" | grep -q 'actually broke'
[ $? -ne 0 ];                            chk "  ...and re-admits none of the text" $?
[ "${#again}" -lt 400 ];                 chk "  ...so the repeat costs almost nothing" $?
# Any difference must break the equality — a stale "unchanged" would be worse than the
# tokens it saves.
# Change what the script PRINTS. Appending after its `exit` would change the file and
# not the output, which is the opposite of what this asserts.
sed -i.bak 's/the thing that actually broke/a different thing broke/' "$NOISE"
changed=$("$CLI/atlas-observe" -- "$NOISE" 2>&1)
printf '%s' "$changed" | grep -q 'unchanged since'
[ $? -ne 0 ];                            chk "changed output is never reported as unchanged" $?

n=$("$CLI/atlas-observe" list 2>&1 | grep -c "^  2")
[ "$n" -ge 3 ];                          chk "list shows the recorded observations" $?
"$CLI/atlas-observe" prune --keep 1 >/dev/null 2>&1
n=$("$CLI/atlas-observe" list 2>&1 | grep -c "^  2")
[ "$n" -eq 1 ];                          chk "prune keeps only what was asked for" $?
"$CLI/atlas" observe -- echo wired >/dev/null 2>&1
chk "reachable as the 'atlas observe' subcommand" $?

# =====================================================================================
t "atlas tickets — the records are the state, every view is derived"
TK="$TMP/tk"; export ATLAS_HOME="$TK"
"$CLI/atlas-init" >/dev/null 2>&1
mkticket() { # id state title next-action
  d="$TK/projects/demo/tickets/$1"; mkdir -p "$d"
  cat > "$d/task.md" <<EOT
---
id: $1
title: $3
state: $2
project: demo
opened: 2026-09-01
updated: 2026-09-01
artifacts: []
class: small
---

## Objective

Prove the record is the state.

## Next action

$4

## Verification

\`echo ok\`

## Blockers

None.

## Log

- 2026-09-01 — HISTORICAL DETAIL THAT MUST NOT REACH THE PACKET
- 2026-09-02 — second entry
EOT
}
mkdir -p "$TK/projects/demo"
mkticket DEMO-001 active "First thing"  "Do the first thing."
mkticket DEMO-002 done   "Second thing" "Complete."
mkticket DEMO-003 blocked "Third thing" "Wait for the owner."
printf '# Work — demo\n\n## Tickets\n\n<!-- atlas:tickets:begin -->\n<!-- atlas:tickets:end -->\n' \
  > "$TK/projects/demo/index.md"

out=$("$CLI/atlas-tickets" list 2>&1)
printf '%s' "$out" | grep -q DEMO-001 && printf '%s' "$out" | grep -q DEMO-003
chk "list derives the live set (active and blocked)" $?
printf '%s' "$out" | grep -q DEMO-002
[ $? -ne 0 ];                            chk "  ...and leaves out what is done" $?

"$CLI/atlas-tickets" doctor >/dev/null 2>&1
[ $? -ne 0 ];                            chk "doctor fails while the generated table is empty" $?
"$CLI/atlas-tickets" index --write >/dev/null 2>&1
chk "index --write generates the board table" $?
grep -q 'DEMO-001' "$TK/projects/demo/index.md"
chk "  ...and the table names the records" $?
"$CLI/atlas-tickets" doctor >/dev/null 2>&1
chk "  ...after which doctor is clean" $?

# Drift is the failure this replaces hand-synchronisation to prevent.
sed -i.bak 's/| DEMO-001 | `active`/| DEMO-001 | `done`/' "$TK/projects/demo/index.md"
out=$("$CLI/atlas-tickets" doctor 2>&1)
printf '%s' "$out" | grep -q 'disagrees with the'
chk "doctor catches a hand-edited table that disagrees with the records" $?
"$CLI/atlas-tickets" index --write >/dev/null 2>&1

# Correction: authority is detected structurally, never by finding the id in prose.
mkdir -p "$TK/personal/daily/2026/09/2026-09-04"
printf 'Worked on DEMO-001 today; state: active; it is done now.\n' \
  > "$TK/personal/daily/2026/09/2026-09-04/log.md"
printf -- '- [WIP] demo — DEMO-001 state: blocked\n' >> "$TK/projects/tasks.md"
"$CLI/atlas-tickets" doctor >/dev/null 2>&1
chk "a ticket id in a daily log or backlog line is a mention, not a declaration" $?

# A second RECORD declaring the same id is a real duplicate, and is an error.
mkdir -p "$TK/projects/other/tickets/DEMO-001"
cp "$TK/projects/demo/tickets/DEMO-001/task.md" "$TK/projects/other/tickets/DEMO-001/task.md"
out=$("$CLI/atlas-tickets" doctor 2>&1)
printf '%s' "$out" | grep -q 'declared by 2 records'
chk "two records declaring one id is refused" $?
rm -rf "$TK/projects/other"

sed -i.bak 's/^artifacts: \[\]/artifacts: [nope.md]/' "$TK/projects/demo/tickets/DEMO-002/task.md"
out=$("$CLI/atlas-tickets" doctor 2>&1)
printf '%s' "$out" | grep -q "which does not exist"
chk "an artifact manifest naming a missing file is refused" $?
sed -i.bak 's/^artifacts: \[nope.md\]/artifacts: []/' "$TK/projects/demo/tickets/DEMO-002/task.md"
rm -f "$TK/projects/demo/tickets/"*/task.md.bak "$TK/projects/demo/index.md.bak"

# =====================================================================================
t "atlas context — a derived cold-start packet, without the history"
"$CLI/atlas-tickets" index --write >/dev/null 2>&1
out=$("$CLI/atlas-context" 2>&1); rc=$?
chk "exits 0" $rc
printf '%s' "$out" | grep -q 'DEMO-001'; chk "names the live tickets" $?
printf '%s' "$out" | grep -q 'DEMO-002'
[ $? -ne 0 ];                            chk "  ...and not the finished ones" $?
printf '%s' "$out" | grep -q 'HISTORICAL DETAIL'
[ $? -ne 0 ];                            chk "admits no log history into the packet" $?

full=$("$CLI/atlas-context" DEMO-001 2>&1)
printf '%s' "$full" | grep -q 'Do the first thing'
chk "a named ticket brings its objective, next action and verification" $?
printf '%s' "$full" | grep -q 'HISTORICAL DETAIL'
chk "  ...and its most recent log lines, which is where that entry belongs" $?
# Soft, not a cap: the packet must stay far cheaper than the records behind it.
recs=$(cat "$TK/projects/demo/tickets/"*/task.md | wc -c)
[ "${#full}" -lt "$recs" ];              chk "the packet is smaller than the records it derives from" $?

"$CLI/atlas-context" NOPE-999 >/dev/null 2>&1
[ $? -ne 0 ];                            chk "an unknown ticket id is refused, not guessed" $?
"$CLI/atlas-context" --json 2>/dev/null | python3 -c "import json,sys;json.load(sys.stdin)"
chk "--json emits valid JSON" $?
b=$("$CLI/atlas-context" --boundary 2>&1)
printf '%s' "$b" | grep -q 'evidence, not a verdict'
chk "--boundary reports signals and states plainly that it decides nothing" $?
printf '%s' "$b" | grep -q 'reconstructs cold.*DEMO-001'
chk "--boundary reports which records reconstruct cold" $?
"$CLI/atlas" context >/dev/null 2>&1
chk "reachable as the 'atlas context' subcommand" $?

# =====================================================================================
t "atlas lifecycle — the decision, and what it refuses to decide"
# The engine is pure, so the decision table is tested directly on evidence rather than
# through a fixture. `decision/sequence` is what a caller acts on.
# Evidence arrives as key=value words, deliberately: a {'k':v} literal is brace-expanded
# by the shell before python ever sees it, which silently split every case into two.
lc() { python3 -c "
import sys
sys.path.insert(0, '$CLI')
import atlas_lifecycle as LC
kw = {}
for a in sys.argv[1:]:
    k, _, v = a.partition('=')
    kw[k] = (True if v == 'True' else False if v == 'False'
             else int(v) if v.lstrip('-').isdigit() else v)
d = LC.decide(LC.evidence(**kw))
print(d['decision'], '+'.join(d['sequence']) or '-', d['certainty'])" "$@"; }
LIVE="has_record=True reconstructable=True task_state=active"
GREW="measured=True turns=80 context_first=20000 context_last=200000"

# 1. A completed task. Its state belongs in the record; the transcript does not.
[ "$(lc $LIVE task_complete=True)" = "FRESH CHECKPOINT+FRESH deterministic" ]
chk "a completed task checkpoints, then starts cold" $?

# 2. The same task, with reasoning that still depends on this context.
[ "$(lc $LIVE measured=True turns=20 context_first=20000 context_last=30000)" \
  = "CONTINUE - deterministic" ]
chk "the same task with unresolved reasoning continues" $?

# 3. Large and stale, with a record that rebuilds it.
[ "$(lc $LIVE $GREW unresolved_reasoning=False)" = "FRESH CHECKPOINT+FRESH recommended" ]
chk "expensive, resolved and reconstructable checkpoints, then starts cold" $?

# 4. Large, and the record could not rebuild it. Losing it is the worse outcome.
[ "$(lc has_record=True reconstructable=False $GREW unresolved_reasoning=False)" \
  = "COMPACT COMPACT recommended" ]
chk "expensive with no safe reconstruction compacts rather than discards" $?
out=$(lc has_record=True reconstructable=False $GREW)
case "$out" in CONTINUE*|COMPACT*) true ;; *) false ;; esac
chk "  ...and never goes fresh with nothing to come back to" $?

# 5. A different, explicitly named workstream.
[ "$(lc $LIVE ticket=A-1 transition_to=B-2)" = "FRESH CHECKPOINT+FRESH deterministic" ]
chk "an explicit transition checkpoints the current task and starts fresh" $?
[ "$(lc $LIVE ticket=A-1 transition_to=A-1)" = "CONTINUE - deterministic" ]
chk "  ...but naming the SAME ticket is not a transition" $?

# 6. Heavy disposable investigation belongs in a worker, not in this context.
[ "$(lc $LIVE disposable_exploration=True)" = "HANDOFF HANDOFF recommended" ]
chk "heavy disposable exploration is isolated in a worker" $?

# 10. THE THRESHOLD GUARD. Relevance decides, not size.
big="measured=True turns=200 context_first=20000 context_last=400000 large_results=20"
out=$(lc $LIVE $big)
case "$out" in CONTINUE*) true ;; *) false ;; esac
chk "a large but still-relevant context is NOT discarded on thresholds alone" $?
printf '%s' "$out" | grep -q 'FRESH'
[ $? -ne 0 ];                            chk "  ...and FRESH appears nowhere in that decision" $?
# One signal is not evidence. A long but flat session has crossed a turn count and
# nothing else.
[ "$(lc $LIVE unresolved_reasoning=False measured=True turns=120 \
        context_first=30000 context_last=31000)" = "CONTINUE - deterministic" ]
chk "a turn count on its own decides nothing — two signals are required" $?

# No record is the one thing that makes a fresh context unsafe.
[ "$(lc has_record=False task_complete=True)" = "CHECKPOINT CHECKPOINT deterministic" ]
chk "a completed task with no record is promoted, not discarded" $?
# COMPACT must not become the habit.
[ "$(lc $LIVE)" = "CONTINUE - deterministic" ]
chk "the default decision is CONTINUE, never COMPACT" $?
[ "$(lc $LIVE unresolved_reasoning=False handoff_open=True)" \
  = "FRESH CHECKPOINT+FRESH recommended" ]
chk "an open handoff already holds the state, so this context is disposable" $?
[ "$(lc $LIVE milestone_done=True)" = "CHECKPOINT CHECKPOINT deterministic" ]
chk "a milestone with no cost signal checkpoints and keeps going" $?
[ "$(lc $LIVE measured=True turns=10 large_results=9)" \
  = "CHECKPOINT CHECKPOINT recommended" ]
chk "raw tool output is a checkpoint, not a reason to restart" $?

# A typo in an evidence field must fail loudly rather than silently defaulting.
python3 -c "
import sys
sys.path.insert(0, '$CLI')
import atlas_lifecycle as LC
try:
    LC.evidence(unresolved_resoning=False)
except KeyError:
    sys.exit(0)
sys.exit(1)"
chk "an unknown evidence field is refused, not quietly ignored" $?

# The measured half maps onto the same vocabulary.
gmap() { python3 -c "
import sys
sys.path.insert(0, '$CLI')
import atlas_lifecycle as LC
print(LC.guard_lifecycle(sys.argv[1], *[a == 'True' for a in sys.argv[2:]])[0])" "$@"; }
[ "$(gmap grew_and_never_fell)" = "FRESH" ]
chk "guard: a session that grew and never fell maps to FRESH" $?
[ "$(gmap grew_and_never_fell True False)" = "CHECKPOINT" ]
chk "  ...but only CHECKPOINT when the record cannot rebuild it" $?
[ "$(gmap large_results)" = "CHECKPOINT" ]
chk "guard: large raw results map to CHECKPOINT" $?
[ "$(gmap strong_model_navigating)" = "HANDOFF" ]
chk "guard: a strong model navigating maps to HANDOFF" $?
[ "$(gmap redundant_reads)" = "CONTINUE" ]
chk "guard: a redundant re-read is not a session boundary" $?

# =====================================================================================
t "atlas lifecycle — against the real records and a measured transcript"
export ATLAS_HOME="$TK"
out=$("$CLI/atlas-lifecycle" --ticket DEMO-001 --transcripts "$TMP/nowhere" 2>&1); rc=$?
chk "exits 0 with no transcript to measure" $rc
printf '%s' "$out" | grep -q 'NOT_MEASURED'
chk "says plainly that nothing was measured, rather than assuming" $?
printf '%s' "$out" | grep -q 'SAFE_RECONSTRUCTION'
chk "reads reconstruction availability from the record" $?

out=$("$CLI/atlas-lifecycle" --ticket DEMO-001 --complete --transcripts "$TMP/nowhere" 2>&1)
printf '%s' "$out" | grep -q 'Context boundary reached'
chk "a completed task prints the boundary" $?
printf '%s' "$out" | grep -q 'atlas context DEMO-001'
chk "  ...and the one command that rebuilds the context" $?
printf '%s' "$out" | grep -q 'atlas tickets checkpoint DEMO-001'
chk "  ...and the checkpoint command, ready to run" $?
printf '%s' "$out" | grep -qi 'no agent can clear or restart'
chk "  ...and does not pretend it can restart the session itself" $?

# The measured path: 70 turns growing 16k -> 430k, from the guard fixture.
out=$("$CLI/atlas-lifecycle" --ticket DEMO-001 --session BIG --resolved \
        --transcripts "${GTX}" 2>&1)
printf '%s' "$out" | grep -q 'CHECKPOINT → FRESH'
chk "a measured runaway session with a safe record goes checkpoint then fresh" $?
printf '%s' "$out" | grep -q 'CONTEXT_GREW_AND_NEVER_FELL'
chk "  ...and names the measured signal it acted on" $?
out=$("$CLI/atlas-lifecycle" --ticket DEMO-001 --session BIG \
        --transcripts "${GTX}" 2>&1)
printf '%s' "$out" | grep -q 'FRESH'
[ $? -ne 0 ];                            chk "  ...and without --resolved it will not go fresh at all" $?

out=$("$CLI/atlas-lifecycle" --transcripts "$TMP/nowhere" 2>&1)
printf '%s' "$out" | grep -q 'pass --ticket'
chk "two live tickets and none named: it asks instead of choosing" $?
"$CLI/atlas-lifecycle" --ticket DEMO-001 --json --transcripts "$TMP/nowhere" 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);sys.exit(0 if d['decision']['signals'] else 1)"
chk "--json carries the decision and every signal behind it" $?
"$CLI/atlas" lifecycle --ticket DEMO-001 --transcripts "$TMP/nowhere" >/dev/null 2>&1
chk "reachable as the 'atlas lifecycle' subcommand" $?

# =====================================================================================
t "atlas lifecycle effort — by class, down for mechanical work, up only with a reason"
eff() { "$CLI/atlas-lifecycle" effort "$@" 2>&1 | sed -n '2p'; }
printf '%s' "$(eff --class small)"  | grep -q 'low'
chk "a small task earns low effort" $?
printf '%s' "$(eff --class medium)" | grep -q 'medium'
chk "a medium task earns medium" $?
printf '%s' "$(eff --class large)"  | grep -q 'high'
chk "architecture-class work earns high" $?
printf '%s' "$(eff --class large --kind ticket-bookkeeping)" | grep -q 'low'
chk "bookkeeping inside a large task is still mechanical, so effort goes DOWN" $?
"$CLI/atlas-lifecycle" effort --class small --want high >/dev/null 2>&1
[ $? -ne 0 ];                            chk "raising effort with no recorded reason is refused" $?
"$CLI/atlas-lifecycle" effort --class small --want high \
  --reason security-sensitive-decision >/dev/null 2>&1
chk "  ...and allowed when the reason is one of the recorded ones" $?
"$CLI/atlas-lifecycle" effort --class small --want max >/dev/null 2>&1
[ $? -ne 0 ];                            chk "an escalation past the ladder with no reason is refused" $?
"$CLI/atlas-lifecycle" effort --class large --json 2>/dev/null | python3 -c "
import json,sys
d = json.load(sys.stdin)
m = d['mechanisms']
sys.exit(0 if d['effort'] == 'high' and 'per_task' not in m and 'process' in m else 1)"
chk "--json names only the mechanisms confirmed to apply it" $?
"$CLI/atlas-lifecycle" effort --doctor --json >/dev/null 2>&1
rc=$?; [ "$rc" = "0" ] || [ "$rc" = "1" ]
chk "--doctor reports rather than crashing, whatever the client is set to" $?

# Confirmed 2026-09-05: a subagent's `effort:` frontmatter is not honored — every
# subagent inherits the parent session's level regardless of what it declares. --doctor
# no longer scans agent frontmatter for it or compares it against models.yaml.
EW="$TMP/effort-ws"; export ATLAS_HOME="$EW"
"$CLI/atlas-init" >/dev/null 2>&1
printf 'effort_by_class:\n  small: low\n  medium: medium\n  large: high\n' \
  > "$EW/internal/config/models.yaml"
echo '{"effortLevel":"medium"}' > "$ATLAS_CLAUDE_SETTINGS"
"$CLI/atlas-lifecycle" effort --doctor >/dev/null 2>&1
chk "clean when the policy and the client agree" $?
# An illegal level in the policy could never have been applied by the client.
printf 'effort_by_class:\n  small: low\n  medium: normal\n  large: high\n' \
  > "$EW/internal/config/models.yaml"
out=$("$CLI/atlas-lifecycle" effort --doctor 2>&1)
printf '%s' "$out" | grep -q 'NOT a client effort level'
chk "a class mapped to a level the client does not have is caught" $?
export ATLAS_HOME="$TK"

# =====================================================================================
t "atlas tickets checkpoint — durable state at a boundary, and nothing else"
before_b=$(wc -c < "$TK/projects/demo/tickets/DEMO-001/task.md")
out=$("$CLI/atlas-tickets" checkpoint DEMO-001 \
        --note "engine written; contract suite green" \
        --next "Wire the guard mapping." 2>&1); rc=$?
chk "exits 0" $rc
grep -q 'engine written; contract suite green' "$TK/projects/demo/tickets/DEMO-001/task.md"
chk "the note is appended to the log" $?
grep -q 'Wire the guard mapping.' "$TK/projects/demo/tickets/DEMO-001/task.md"
chk "the next action is REPLACED, not appended — the record's action is the live one" $?
grep -q 'Do the first thing' "$TK/projects/demo/tickets/DEMO-001/task.md"
[ $? -ne 0 ];                            chk "  ...so the superseded action is gone" $?
grep -q 'Prove the record is the state' "$TK/projects/demo/tickets/DEMO-001/task.md"
chk "no other section is touched" $?
grep -q "^updated: $(date +%F)" "$TK/projects/demo/tickets/DEMO-001/task.md"
chk "updated: is bumped" $?
after_b=$(wc -c < "$TK/projects/demo/tickets/DEMO-001/task.md")
[ $((after_b - before_b)) -lt 400 ]
chk "a checkpoint costs a record a few hundred bytes, not a transcript" $?
printf '%s' "$out" | grep -q 'atlas context DEMO-001'
chk "  ...and it names how to resume cold" $?

# Checkpointing after every small turn would trade one waste for another.
out=$("$CLI/atlas-tickets" checkpoint DEMO-001 \
        --note "engine written; contract suite green" 2>&1)
printf '%s' "$out" | grep -q 'already current'
chk "the same note with no new action writes nothing at all" $?
before=$(shasum "$TK/projects/demo/tickets/DEMO-001/task.md")
"$CLI/atlas-tickets" checkpoint DEMO-001 --note "engine written; contract suite green" \
  >/dev/null 2>&1
after=$(shasum "$TK/projects/demo/tickets/DEMO-001/task.md")
[ "$before" = "$after" ];                chk "  ...and the file is byte-identical afterwards" $?

"$CLI/atlas-tickets" checkpoint DEMO-001 --note "paused for the owner" \
  --state paused >/dev/null 2>&1
grep -q '^state: paused' "$TK/projects/demo/tickets/DEMO-001/task.md"
chk "--state moves the one place a status is declared" $?
"$CLI/atlas-tickets" checkpoint DEMO-001 --note "back to work" --state active >/dev/null 2>&1
"$CLI/atlas-tickets" checkpoint NOPE-999 --note "x" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "an unknown ticket is refused" $?
"$CLI/atlas-tickets" checkpoint DEMO-001 >/dev/null 2>&1
[ $? -ne 0 ];                            chk "a checkpoint with no note is refused — a boundary needs a record" $?
# A checkpoint moves the next action, which the generated board shows. Leaving that view
# stale would mean every clean boundary ended with doctor failing.
"$CLI/atlas-tickets" checkpoint DEMO-001 --note "regenerates the board" \
  --next "Check the board regenerated." >/dev/null 2>&1
grep -q 'Check the board regenerated' "$TK/projects/demo/index.md"
chk "a checkpoint regenerates the board it just made stale" $?
"$CLI/atlas-tickets" doctor >/dev/null 2>&1
chk "  ...so the records and every view of them are clean with no second command" $?

# =====================================================================================
t "doctor: a worktree of the same repo is not a nested repository"
WT="$TMP/wt-home"; mkdir -p "$WT"
export ATLAS_HOME="$WT"
"$CLI/atlas-init" >/dev/null 2>&1
git -C "$WT" init -q; git -C "$WT" config user.email t@e; git -C "$WT" config user.name t
git -C "$WT" add -A >/dev/null 2>&1; git -C "$WT" commit -qm base >/dev/null 2>&1
git -C "$WT" worktree add -q "$WT/.claude/worktrees/session" -b wt-session >/dev/null 2>&1
out=$("$CLI/atlas-doctor" 2>&1)
printf '%s' "$out" | grep -q "private workspace: no nested repositories"
chk "the repo's own worktree is not reported as nested" $?
# The check must still catch what it exists for: a DIFFERENT repository hiding inside.
git -C "$WT" worktree remove --force "$WT/.claude/worktrees/session" >/dev/null 2>&1
mkdir -p "$WT/vendor/foreign"; git -C "$WT/vendor/foreign" init -q
out=$("$CLI/atlas-doctor" 2>&1)
printf '%s' "$out" | grep -q "nested git repository inside the private workspace"
chk "a genuinely foreign nested repository is still a failure" $?
rm -rf "$WT/vendor"

# =====================================================================================
t "privacy-scan: an ignored DIRECTORY exempts what is inside it"
# git names the directory, not its contents, whenever it will not descend — an excluded
# directory, and always a nested repository or worktree. Matching whole paths against that
# set treated every file inside one as publishable.
PS="$TMP/ps-repo"; mkdir -p "$PS/.claude/worktrees/wt" "$PS/src"
git -C "$PS" init -q 2>/dev/null
printf '.claude/worktrees/\n' > "$PS/.gitignore"
# Built from parts: writing the literal path here would put an absolute home path into
# this repository, which is the very thing the scanner is right to refuse.
printf 'gitdir: /%s/%s/p/.git/worktrees/wt\n' Users someone > "$PS/.claude/worktrees/wt/.git"
printf 'clean source\n' > "$PS/src/ok.txt"
out=$("$CLI/atlas-privacy-scan" "$PS" 2>&1); rc=$?
chk "exits 0 when the only home path is inside an ignored directory" $rc
printf '%s' "$out" | grep -q 'PERSONAL'
[ $? -ne 0 ];                            chk "  ...and reports no personal finding for it" $?
# The exemption is for personal data only. A credential inside an ignored path is still
# a credential, and must still be found.
printf 'aws_secret_access_key = %s%s\n' AKIA IOSFODNN7EXAMPLE > "$PS/.claude/worktrees/wt/creds"
"$CLI/atlas-privacy-scan" "$PS" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "a credential inside an ignored path is still refused" $?

# =====================================================================================
t "atlas usage — measures transcripts, mutates nothing"
U="$TMP/usage-transcripts"; mkdir -p "$U/proj-a/sess-super/subagents/workflows/wf_1"
# One assistant turn written as THREE lines that repeat the same usage object — exactly
# how the client records a multi-block turn. Counting lines would report three turns.
mkusage() { # output_tokens cache_read cache_write
  printf '{"input_tokens":0,"cache_read_input_tokens":%s,"cache_creation_input_tokens":%s,"cache_creation":{"ephemeral_5m_input_tokens":%s,"ephemeral_1h_input_tokens":0},"output_tokens":%s,"output_tokens_details":{"thinking_tokens":1}}' "$2" "$3" "$3" "$1"
}
BIG=$(head -c 9000 /dev/zero | tr '\0' 'x')
{
  for i in 1 2 3; do
    printf '{"type":"assistant","sessionId":"S1","timestamp":"2026-09-01T00:00:0%sZ","cwd":"/w","message":{"id":"m1","model":"claude-sonnet-5","usage":%s,"content":[{"type":"tool_use","id":"tu%s","name":"Read","input":{"file_path":"/w/a.txt"}}]}}\n' "$i" "$(mkusage 100 5000 200)" "$i"
  done
  printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu1","content":"SAME"}]}}\n'
  printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu2","content":"SAME"}]}}\n'
  printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tu3","content":"CHANGED"}]}}\n'
  printf '{"type":"assistant","sessionId":"S1","timestamp":"2026-09-01T00:00:09Z","cwd":"/w","message":{"id":"m2","model":"claude-opus-5","usage":%s,"content":[{"type":"tool_use","id":"tb","name":"Bash","input":{"command":"ls"}}]}}\n' "$(mkusage 50 6000 100)"
  printf '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"tb","content":"%s"}]}}\n' "$BIG"
} > "$U/proj-a/S1.jsonl"
# A worker transcript nested two levels below subagents/ — not a main session.
printf '{"type":"assistant","sessionId":"S1","timestamp":"2026-09-01T00:00:05Z","message":{"id":"w1","model":"claude-haiku-4-5","usage":%s,"content":[]}}\n' "$(mkusage 10 100 10)" > "$U/proj-a/sess-super/subagents/workflows/wf_1/agent-x.jsonl"
# Two files for one session id: a prefix, and the longer continuation of it.
printf '{"type":"assistant","sessionId":"S2","timestamp":"2026-09-02T00:00:01Z","message":{"id":"p1","usage":%s,"content":[]}}\n' "$(mkusage 10 7000 10)" > "$U/proj-a/S2-prefix.jsonl"
{ printf '{"type":"assistant","sessionId":"S2","timestamp":"2026-09-02T00:00:01Z","message":{"id":"p1","usage":%s,"content":[]}}\n' "$(mkusage 10 7000 10)"
  printf '{"type":"assistant","sessionId":"S2","timestamp":"2026-09-02T00:00:02Z","message":{"id":"p2","usage":%s,"content":[]}}\n' "$(mkusage 10 7000 10)"
} > "$U/proj-a/S2-full.jsonl"

before=$(find "$U" -type f -exec shasum {} \; | sort | shasum)
J="$TMP/usage.json"
"$CLI/atlas-usage" --transcripts "$U" --json > "$J" 2>/dev/null; rc=$?
chk "exits 0 with transcripts present" $rc
python3 -c "import json;json.load(open('$J'))" 2>/dev/null;    chk "--json emits valid JSON" $?
after=$(find "$U" -type f -exec shasum {} \; | sort | shasum)
[ "$before" = "$after" ];                chk "measuring changed no transcript" $?

q() { python3 -c "
import json,sys
d=json.load(open('$J'))
s={r['session_id']:r for r in d['sessions'] if not r['is_subagent']}
print(eval(sys.argv[1]))" "$1"; }

[ "$(q "d['aggregate']['main_sessions']")" = "2" ]
chk "counts 2 main sessions — the worker and the superseded prefix are not main" $?
[ "$(q "d['aggregate']['subagent_sessions']")" = "1" ]
chk "a worker nested under subagents/workflows/ counts as a subagent" $?
[ "$(q "s['S1']['turns']")" = "2" ]
chk "one turn split across three lines counts once (message.id dedup)" $?
[ "$(q "s['S1']['totals']['output']")" = "150" ]
chk "output is not multiplied by the block count" $?
[ "$(q "s['S1']['totals']['cache_read']")" = "11000" ]
chk "cache-read is not multiplied by the block count" $?
[ "$(q "s['S2']['turns']")" = "2" ]
chk "the longer file wins supersession, the prefix is dropped" $?
# 11,000 (S1) + 14,000 (S2 continuation) + 100 (worker) = 25,100.
# Billing the superseded prefix as well would read 32,100.
[ "$(q "d['aggregate']['totals']['cache_read']")" = "25100" ]
chk "the superseded prefix's tokens are not billed twice" $?
"$CLI/atlas-usage" --transcripts "$U" --json --include-superseded 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);sys.exit(0 if d['aggregate']['main_sessions']==3 else 1)"
chk "--include-superseded restores the dropped prefix" $?
[ "$(q "s['S1']['large_results']['count']")" = "1" ]
chk "a tool result over the reporting threshold is flagged" $?
[ "$(q "s['S1']['repeated_reads']['redundant_calls']")" = "1" ]
chk "a re-read returning identical content counts as redundant" $?
[ "$(q "s['S1']['repeated_reads']['repeat_calls']")" = "2" ]
chk "a re-read returning changed content is a repeat but not redundant" $?
[ "$(q "sorted(s['S1']['models'])")" = "['claude-opus-5', 'claude-sonnet-5']" ]
chk "per-session model usage is observable" $?
"$CLI/atlas-usage" --transcripts "$TMP/no-such-dir" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "refuses when no transcripts exist" $?
"$CLI/atlas-usage" --transcripts "$U" --since 2026-09-02 --json 2>/dev/null \
  | python3 -c "import json,sys;d=json.load(sys.stdin);sys.exit(0 if d['aggregate']['main_sessions']==1 else 1)"
chk "--since filters by the last turn's date" $?
"$CLI/atlas" usage --transcripts "$U" >/dev/null 2>&1
chk "reachable as the 'atlas usage' subcommand" $?

# The benchmark view: a recorded baseline against the cohort measured now. Without it a
# before/after claim is arithmetic done by hand, which is how a saving gets asserted
# before any post-change session exists.
B2="$TMP/bench.json"
"$CLI/atlas-usage" --transcripts "$U" --baseline "$B2" >/dev/null 2>&1
out=$("$CLI/atlas-usage" --transcripts "$U" --compare "$B2" 2>&1); rc=$?
chk "--compare exits 0 against a baseline it wrote" $rc
printf '%s' "$out" | grep -q 'before' && printf '%s' "$out" | grep -q 'after'
chk "  ...and prints both columns" $?
printf '%s' "$out" | grep -qi 'not yet a saving'
chk "  ...and refuses to call an unchanged cohort a saving" $?
"$CLI/atlas-usage" --transcripts "$U" --compare "$TMP/no-baseline.json" >/dev/null 2>&1
[ $? -ne 0 ];                            chk "a missing baseline is refused, not invented" $?
[ "$(q "d['aggregate']['cache_read_per_turn_median']")" != "None" ]
chk "the aggregate carries a median re-read per turn, not only a mean" $?

# The high-effort rate is the number that says whether effort routing changed anything.
EFT="$TMP/effort-tx"; mkdir -p "$EFT/p"
ef() { printf '{"type":"assistant","effort":"%s","sessionId":"E1","timestamp":"2026-09-01T00:00:00Z","message":{"id":"%s","model":"claude-sonnet-5","usage":{"input_tokens":1,"cache_read_input_tokens":10,"cache_creation_input_tokens":0,"output_tokens":1,"output_tokens_details":{"thinking_tokens":1}},"content":[]}}\n' "$1" "$2"; }
{ ef high e1; ef xhigh e2; ef low e3; ef medium e4; } > "$EFT/p/E1.jsonl"
"$CLI/atlas-usage" --transcripts "$EFT" --json 2>/dev/null | python3 -c "
import json,sys
d = json.load(sys.stdin)
sys.exit(0 if d['aggregate']['high_effort_rate_pct'] == 50.0 else 1)"
chk "high/xhigh/max are counted as high effort, and the rate is measured not assumed" $?

# The same block-per-turn trap that inflated turns by 1.8x also inflated effort: one turn
# is several lines and every one repeats the effort. Measured on a real transcript it
# read 196 where there were 114 turns — in the exact number effort routing is judged by.
EFT2="$TMP/effort-blocks"; mkdir -p "$EFT2/p"
ef2() { printf '{"type":"assistant","effort":"%s","sessionId":"E2","timestamp":"2026-09-01T00:00:00Z","message":{"id":"%s","model":"claude-sonnet-5","usage":{"input_tokens":1,"cache_read_input_tokens":10,"cache_creation_input_tokens":0,"output_tokens":1,"output_tokens_details":{"thinking_tokens":1}},"content":[]}}\n' "$1" "$2"; }
{ ef2 high d1; ef2 high d1; ef2 high d1; ef2 low d2; ef2 low d2; } > "$EFT2/p/E2.jsonl"
"$CLI/atlas-usage" --transcripts "$EFT2" --session E2 --json 2>/dev/null | python3 -c "
import json,sys
d = json.load(sys.stdin)
sys.exit(0 if (d['turns'] == 2 and sum(d['effort'].values()) == 2
               and d['effort'] == {'high': 1, 'low': 1}) else 1)"
chk "effort is counted once per turn, not once per content block" $?

# =====================================================================================
t "atlas usage --models — parent/worker identity from transcript evidence only"
MU="$TMP/usage-models"; mkdir -p "$MU/proj/P2/subagents"
mu() { # output_tokens cache_read cache_write
  printf '{"input_tokens":0,"cache_read_input_tokens":%s,"cache_creation_input_tokens":%s,"cache_creation":{"ephemeral_5m_input_tokens":%s,"ephemeral_1h_input_tokens":0},"output_tokens":%s,"output_tokens_details":{"thinking_tokens":0}}' "$2" "$3" "$3" "$1"
}
# P1: a parent with no workers at all.
{ printf '{"type":"assistant","effort":"high","sessionId":"P1","timestamp":"2026-09-01T00:00:00Z","message":{"id":"p1a","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 10 1)"
  printf '{"type":"assistant","effort":"high","sessionId":"P1","timestamp":"2026-09-01T00:00:01Z","message":{"id":"p1b","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 10 1)"
} > "$MU/proj/P1.jsonl"
# P2: a parent (sonnet, medium) with two workers.
{ printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:00Z","message":{"id":"q1","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 10 1)"
  printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:01Z","message":{"id":"q2","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 10 1)"
  printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:02Z","message":{"id":"q3","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 10 1)"
} > "$MU/proj/P2.jsonl"
# Worker "architect": model overridden to opus, effort matches the parent's (medium) ->
# inherited. Its one real turn is written three times with the SAME message.id, exactly
# how one multi-block turn is recorded — must count as 1 turn, not 3.
{ printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:03Z","message":{"id":"w1","model":"claude-opus-5","usage":%s,"content":[{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}\n' "$(mu 1 20 1)"
  printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:03Z","message":{"id":"w1","model":"claude-opus-5","usage":%s,"content":[{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}\n' "$(mu 1 20 1)"
  printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:03Z","message":{"id":"w1","model":"claude-opus-5","usage":%s,"content":[{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}\n' "$(mu 1 20 1)"
  printf '{"type":"assistant","effort":"medium","sessionId":"P2","timestamp":"2026-09-01T00:00:04Z","message":{"id":"w2","model":"claude-opus-5","usage":%s,"content":[]}}\n' "$(mu 1 20 1)"
} > "$MU/proj/P2/subagents/agent-arch.jsonl"
printf '{"agentType":"architect"}' > "$MU/proj/P2/subagents/agent-arch.meta.json"
# Worker "debugger": same model as the parent (no override), no effort field recorded at
# all -> unknown, not assumed inherited.
printf '{"type":"assistant","sessionId":"P2","timestamp":"2026-09-01T00:00:05Z","message":{"id":"d1","model":"claude-sonnet-5","usage":%s,"content":[]}}\n' "$(mu 1 5 1)" > "$MU/proj/P2/subagents/agent-dbg.jsonl"
printf '{"agentType":"debugger"}' > "$MU/proj/P2/subagents/agent-dbg.meta.json"

MJ="$TMP/usage-models.json"
"$CLI/atlas-usage" --transcripts "$MU" --models --session P1 --json > "$MJ" 2>/dev/null
chk "--models --session exits 0 for a parent-only session" $?
python3 -c "import json;json.load(open('$MJ'))" >/dev/null 2>&1
chk "  ...and emits valid JSON" $?
[ "$(python3 -c "import json;d=json.load(open('$MJ'));print(d['workers'])")" = "[]" ]
chk "a parent with no worker transcripts reports an empty worker list" $?
"$CLI/atlas-usage" --transcripts "$MU" --models --session P1 2>/dev/null | grep -q '^Workers$'
chk "  ...and the human view prints a Workers section" $?
"$CLI/atlas-usage" --transcripts "$MU" --models --session P1 2>/dev/null | grep -qx '  none'
chk "  ...saying 'none', not an empty list" $?
[ "$(python3 -c "import json;d=json.load(open('$MJ'));print(d['parent']['model'])")" = "claude-sonnet-5" ]
chk "parent model is read from the transcript" $?
[ "$(python3 -c "import json;d=json.load(open('$MJ'));print(d['parent']['effort'])")" = "high" ]
chk "parent effort is read from the transcript" $?
[ "$(python3 -c "import json;d=json.load(open('$MJ'));print(d['parent']['turns'])")" = "2" ]
chk "parent turns match the deduplicated count" $?

MJ2="$TMP/usage-models-p2.json"
"$CLI/atlas-usage" --transcripts "$MU" --models --session P2 --json > "$MJ2" 2>/dev/null
chk "--models --session exits 0 for a parent with workers" $?
python3 -c "import json;json.load(open('$MJ2'))" >/dev/null 2>&1
chk "  ...and emits valid JSON" $?
[ "$(python3 -c "import json;d=json.load(open('$MJ2'));print(len(d['workers']))")" = "2" ]
chk "both workers are found and grouped under their parent's session_id" $?
wq() { python3 -c "
import json, sys
d=json.load(open('$MJ2'))
w={x['agent_type']:x for x in d['workers']}
print(eval(sys.argv[1]))" "$1"; }
[ "$(wq "w['architect']['model']")" = "claude-opus-5" ]
chk "worker agent_type comes from the sibling .meta.json" $?
[ "$(wq "w['architect']['model_override']")" = "True" ]
chk "opus worker under a sonnet parent is reported as a model override" $?
[ "$(wq "w['architect']['turns']")" = "2" ]
chk "  ...and its turns are deduplicated (one message.id split across 3 lines counts once)" $?
[ "$(wq "w['architect']['effort']")" = "medium" ]
chk "worker effort matching the parent's recorded effort is surfaced" $?
[ "$(wq "w['architect']['effort_source']")" = "inherited" ]
chk "  ...and classified as inherited, not asserted from policy" $?
[ "$(wq "w['debugger']['model_override']")" = "False" ]
chk "a worker on the same model as its parent is not flagged as an override" $?
[ "$(wq "w['debugger']['effort']")" = "unknown" ]
chk "a worker with no recorded effort field reports unknown, not a guessed value" $?
[ "$(wq "w['debugger']['effort_source']")" = "unknown" ]
chk "  ...and inheritance is not claimed without evidence" $?
"$CLI/atlas-usage" --transcripts "$MU" --models --session P2 2>/dev/null | grep -q 'architect'
chk "human view lists each worker by its agent_type" $?
"$CLI/atlas-usage" --transcripts "$MU" --session P1 --json >/dev/null 2>&1
chk "plain 'atlas usage --session' (no --models) still works unchanged" $?

# =====================================================================================
t "response protocol contract"
RESP="$HOME/atlas/internal/governance/policies/response.md"
if [ -f "$RESP" ]; then
  # Lazy: the module lives in policies/, not in the always-loaded bootstrap.
  ! grep -q 'QUICK_RESULT\|EXECUTION_REPORT' "$REAL_CORE" 2>/dev/null
  chk "core.md does not carry the response modes — they stay lazy-loaded" $?
  for mode in QUICK_RESULT EXECUTION_REPORT TECHNICAL_EXPLANATION BLOCKER DECISION_REQUIRED PROMPT_ARTIFACT BILINGUAL; do
    grep -q "$mode" "$RESP"
    chk "  ...defines $mode" $?
  done
  grep -qi 'smallest response shape' "$RESP"
  chk "  ...states the governing principle" $?
  grep -q 'bold sparingly' "$RESP"
  chk "  ...still says use bold sparingly" $?
  grep -q 'meaningful event' "$RESP"
  chk "  ...progress updates are gated on meaningful events, not every tool call" $?
else
  printf '  %sSKIP%s no private workspace on this machine\n' "$D" "$X"
fi

# Client-aware honesty: only a client with a real enforcement mechanism claims one.
CC_ADAPTER="$REPO/adapters/claude-code/adapter.yaml"
if [ -f "$CC_ADAPTER" ]; then
  grep -q 'enforces:.*response' "$CC_ADAPTER"
  chk "claude-code adapter claims response enforcement, and it has a hook for it" $?
  [ -x "$REPO/adapters/claude-code/ai-response-gate" ]
  chk "  ...ai-response-gate exists and is executable" $?
fi
for c in codex gemini; do
  A="$REPO/adapters/$c/adapter.yaml"
  if [ -f "$A" ]; then
    grep -q 'enforces: \[\]' "$A"
    chk "$c adapter does not claim enforcement it cannot deliver" $?
  fi
done

# =====================================================================================
t "inherited suites still pass"
unset ATLAS_HOME   # these exercise the real private workspace, not a fixture home
if [ -f "$REPO/adapters/claude-code/tests/test-guard-push.py" ]; then
  python3 "$REPO/adapters/claude-code/tests/test-guard-push.py" >/dev/null 2>&1
  chk "claude-code git push guard" $?
else
  printf '  %sSKIP%s claude-code push guard tests not found\n' "$D" "$X"
fi
if [ -f "$REPO/adapters/claude-code/tests/test-response-gate.py" ]; then
  python3 "$REPO/adapters/claude-code/tests/test-response-gate.py" >/dev/null 2>&1
  chk "claude-code Arabic response gate" $?
else
  printf '  %sSKIP%s claude-code response gate tests not found\n' "$D" "$X"
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
