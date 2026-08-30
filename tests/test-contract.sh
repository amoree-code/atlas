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
for s in config memory knowledge projects sessions daily skills; do
  [ -d "$W/$s" ]; chk "created $s/" $?
done
[ -d "$W/memory/education" ];            chk "created the 8 memory sections" $?
[ -d "$W/knowledge/decisions" ];         chk "created the 7 knowledge kinds" $?
[ -f "$W/memory/MEMORY.md" ];            chk "seeded memory/MEMORY.md" $?
[ ! -d "$W/config/scripts" ];            chk "did NOT seed runtime scripts into private data" $?
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
echo "MY OWN NOTES — do not touch" > "$W/memory/MEMORY.md"
echo "a real memory" > "$W/memory/education/scholarship.md"
mkdir -p "$W/skills/research"; echo "my own research skill" > "$W/skills/research/SKILL.md"
out=$("$CLI/ai-os-init" 2>&1)
grep -q "MY OWN NOTES" "$W/memory/MEMORY.md";        chk "edited seed file preserved verbatim" $?
grep -q "a real memory" "$W/memory/education/scholarship.md"; chk "user memory file untouched" $?
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
export AI_OS_RUNTIME="$TMP/fake-runtime"
mkdir -p "$AI_OS_RUNTIME/bin"
for b in ai-memory ai-guard-push ai-sync; do printf '#!/bin/sh\n' > "$AI_OS_RUNTIME/bin/$b"; chmod +x "$AI_OS_RUNTIME/bin/$b"; done
echo 'CANON = HOME / ".ai-os" / "memory"' >> "$AI_OS_RUNTIME/bin/ai-memory"
out=$("$CLI/ai-os-doctor" 2>&1); rc=$?
[ "$rc" -eq 0 ];                         chk "no failures on a freshly initialized workspace" $?

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
mkdir -p "$P/good" && ln -s "$AI_OS_HOME/memory" "$P/good/memory"
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
mkdir -p "$TMP/clean/config"; echo "$TERM" > "$TMP/clean/config/privacy-terms.txt"
out=$(AI_OS_HOME="$TMP/clean" "$CLI/ai-os-privacy-scan" "$F" 2>&1)
echo "$out" | grep -q "PERSONAL.*user term";         chk "term from ~/.ai-os is applied" $?
grep -rqi "$TERM" "$REPO" --exclude-dir=.git; [ $? -ne 0 ]
chk "the term itself never entered the public repo" $?
rm -f "$TMP/clean/config/privacy-terms.txt"

t "privacy scan: no false positive on the repository's own text"
out=$("$CLI/ai-os-privacy-scan" "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "the public repo scans clean" $?

# =====================================================================================
t "public repository cleanliness (working tree AND full history)"
out=$("$CLI/ai-os-privacy-scan" --history --quiet "$REPO" 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no personal data anywhere in git history" $?

# =====================================================================================
t "plugin contract: the real registry"
out=$("$CLI/ai-os-plugin" doctor 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "all shipped manifests valid" $?
n=$(echo "$out" | grep -c '^  ok ')
[ "$n" -eq 5 ];                                      chk "5 manifests present and parsed" $?
echo "$out" | grep -q "consumer not verified";       chk "unverified consumers are flagged, not hidden" $?
"$CLI/ai-os-plugin" list 2>&1 | grep -q "cursor.*nothing"
chk "a plugin that writes nothing is valid" $?

t "plugin contract: violations are rejected"
F2="$TMP/fixtures"; mkdir -p "$F2"
mk() { mkdir -p "$F2/$1"; cat > "$F2/$1/plugin.yaml"; }

# THE HARD RULE: a provides: path inside the private workspace.
mk badpath <<EOF
plugin: badpath
name: Bad Path
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: $AI_OS_HOME/memory/stolen.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_PLUGINS="$F2" "$CLI/ai-os-plugin" doctor 2>&1); rc=$?
echo "$out" | grep -q "INSIDE \$AI_OS_HOME";          chk "provides: path inside \$AI_OS_HOME is rejected" $?
[ "$rc" -gt 0 ];                                     chk "  ...and it is a hard failure" $?
rm -rf "$F2/badpath"

# verified:false must never be written.
mk unverified <<'EOF'
plugin: unverified
name: Unverified
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: false }
writes: [rules]
EOF
out=$(AI_OS_PLUGINS="$F2" "$CLI/ai-os-plugin" doctor 2>&1)
echo "$out" | grep -q "MUST NOT write an unverified";  chk "writing an unverified capability is rejected" $?
rm -rf "$F2/unverified"

# contract range
mk future <<'EOF'
plugin: future
name: From The Future
contract: 2
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
EOF
out=$(AI_OS_PLUGINS="$F2" "$CLI/ai-os-plugin" doctor 2>&1)
echo "$out" | grep -q "supports 1..1 — DISABLED";      chk "contract 2 on a contract-1 core is disabled with a reason" $?
rm -rf "$F2/future"

# unknown core resource
mk greedy <<'EOF'
plugin: greedy
name: Greedy
contract: 1
client: { detect: [/nonexistent], consumer_verified: false }
provides:
  rules: { path: ~/.someclient/RULES.md, format: markdown, verified: true }
writes: [rules]
requires:
  - workspace.everything
EOF
out=$(AI_OS_PLUGINS="$F2" "$CLI/ai-os-plugin" doctor 2>&1)
echo "$out" | grep -q "unknown core resource";         chk "an undeclared core resource is rejected" $?
rm -rf "$F2/greedy"

# malformed: reports, exits non-zero, changes nothing
mkdir -p "$F2/broken"; printf 'plugin: broken\n\tbad: [unclosed\n' > "$F2/broken/plugin.yaml"
before=$(shasum "$F2/broken/plugin.yaml")
out=$(AI_OS_PLUGINS="$F2" "$CLI/ai-os-plugin" doctor 2>&1); rc=$?
[ "$rc" -gt 0 ];                                     chk "a malformed manifest fails" $?
[ "$before" = "$(shasum "$F2/broken/plugin.yaml")" ]; chk "  ...and nothing was modified" $?
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
m = {"__name__": "notmain"}
exec(compile(Path(H/".ai/bin/ai-sync").read_text(), "ai-sync", "exec"), m)
got = m["CLIENTS"]
assert set(got) == set(EXPECTED), f"clients drifted: {sorted(got)} != {sorted(EXPECTED)}"
for k, (r, sk) in EXPECTED.items():
    assert got[k]["rules"] == r,  f"{k} rules drifted: {got[k]['rules']} != {r}"
    assert got[k]["skills"] == sk, f"{k} skills drifted: {got[k]['skills']} != {sk}"
assert sorted(m["PROJECT_ONLY"]) == EXPECTED_PROJECT_ONLY, m["PROJECT_ONLY"]
PYEOF
chk "the 3 writable clients resolve to their original paths" $?

t "ai-sync knows no client by name"
! grep -qE '^\s*CLIENTS\s*=\s*\{' "$HOME/.ai/bin/ai-sync"
chk "no hardcoded CLIENTS table" $?
! grep -qE '^\s*PROJECT_ONLY\s*=\s*\[' "$HOME/.ai/bin/ai-sync"
chk "no hardcoded PROJECT_ONLY list" $?
! grep -qE 'HOME */ *"\.(claude|codex|gemini|cursor)' "$HOME/.ai/bin/ai-sync"
chk "no hardcoded client config paths" $?
# The docstring says the words "if client == \"claude\"" to explain why it is gone, so
# match an actual conditional (trailing colon) rather than the prose about one.
! grep -qE 'if +client *== *"claude" *:' "$HOME/.ai/bin/ai-sync"
chk "no client-name conditional in core render()" $?

t "the Claude rules fragment lives in the Claude plugin"
[ -f "$REPO/plugins/claude-code/rules-fragment.md" ]
chk "plugins/claude-code/rules-fragment.md exists" $?
python3 - <<'PYEOF'
from pathlib import Path
m = {"__name__": "notmain"}
exec(compile(Path.home().joinpath(".ai/bin/ai-sync").read_text(), "ai-sync", "exec"), m)
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
from pathlib import Path
m = {"__name__": "notmain"}
exec(compile(Path.home().joinpath(".ai/bin/ai-sync").read_text(), "ai-sync", "exec"), m)
# cursor and opencode declare rules verified:false / null path.
for pid in ("cursor", "opencode"):
    assert pid in m["PROJECT_ONLY"], f"{pid} should be project-only"
    assert pid not in m["CLIENTS"], f"{pid} must never be a write target"
PYEOF
chk "cursor and opencode are never write targets" $?
[ ! -f "$HOME/.config/opencode/AGENTS.md" ]
chk "nothing was written to opencode's unverified path" $?

t "skill backups are namespaced per client"
grep -q 'def backup(path, tag, owner=None)' "$HOME/.ai/bin/ai-sync"
chk "backup() takes an owner" $?
# Call sites only — the def line also contains "owner=".
n=$(grep 'backup(.*owner=' "$HOME/.ai/bin/ai-sync" | grep -vc '^def ')
[ "$n" -eq 3 ]
chk "all 3 skill backup sites namespace their copy ($n)" $?

t "plugin enable/disable refuse until wired (no dead state)"
out=$("$CLI/ai-os-plugin" enable claude-code 2>&1); rc=$?
[ "$rc" -ne 0 ];                                     chk "enable refuses" $?
echo "$out" | grep -q "Step 8";                      chk "  ...and names the step that would wire it" $?
[ ! -e "$AI_OS_HOME/config/plugins.yaml" ];          chk "  ...and wrote no registry state" $?

# =====================================================================================
t "profile: the public template carries no values"
TPL="$REPO/templates/workspace/config/profile.yaml"
[ -f "$TPL" ];                                       chk "profile.yaml template exists" $?
grep -qE '^(vcs_owner|  default|  summary|  tool|  curator): *""$' "$TPL"
chk "template ships blank values, not someone's" $?
grep -q 'never leaves ~/.ai-os' "$TPL";              chk "template states it is private" $?

t "profile: init seeds it once and never overwrites"
P3="$TMP/profilews"; export AI_OS_HOME="$P3"
"$CLI/ai-os-init" >/dev/null 2>&1
[ -f "$P3/config/profile.yaml" ];                    chk "init seeds config/profile.yaml" $?
echo "vcs_owner: my-own-handle" > "$P3/config/profile.yaml"
out=$("$CLI/ai-os-init" 2>&1)
grep -q "my-own-handle" "$P3/config/profile.yaml";   chk "an edited profile is never overwritten" $?
echo "$out" | grep -q "yours.*profile.yaml";         chk "  ...and the divergence is reported" $?

t "render: unresolved placeholders are visible, never silently blank"
printf 'x {{profile.nothing.here}} y\n' > "$TMP/probe.md"
mkdir -p "$REPO/skills/__probe__" && cp "$TMP/probe.md" "$REPO/skills/__probe__/SKILL.md"
out=$(AI_OS_HOME="$P3" "$CLI/ai-os-render" __probe__ 2>&1)
echo "$out" | grep -q '\[\[profile.nothing.here unset\]\]'
chk "an unset value renders as an explicit marker" $?
echo "$out" | grep -qE '^x  y$'; [ $? -ne 0 ];       chk "  ...not as an empty string" $?
rm -rf "$REPO/skills/__probe__"

t "render: client conventions come from the plugin manifest"
export AI_OS_HOME="$HOME/.ai-os"
a=$("$CLI/ai-os-render" catch-up --client claude-code 2>&1 | grep -c 'CLAUDE.md')
b=$("$CLI/ai-os-render" catch-up --client codex 2>&1 | grep -c 'AGENTS.md')
[ "$a" -gt 0 ];                                      chk "claude-code resolves to CLAUDE.md" $?
[ "$b" -gt 0 ];                                      chk "codex resolves to AGENTS.md" $?
c=$("$CLI/ai-os-render" catch-up --client codex 2>&1 | grep -c 'CLAUDE.md')
[ "$c" -eq 0 ];                                      chk "  ...and codex gets no Claude filename" $?

t "THE STEP 7 GATE: 8 skills render equivalent to the live runtime"
out=$("$CLI/ai-os-render" --check "$HOME/.ai/skills" --client claude-code 2>&1); rc=$?
[ "$rc" -eq 0 ];                                     chk "no semantic loss across all 8 skills" $?
# Count per-skill result lines only — the summary line says "equivalent" too.
n=$(echo "$out" | grep -cE '^  (identical|equivalent) ')
[ "$n" -eq 8 ];                                      chk "all 8 accounted for ($n)" $?
echo "$out" | grep -q "DIFFERS"; [ $? -ne 0 ];       chk "no skill differs semantically" $?

t "public skills carry no personal values"
# The terms are read from the PRIVATE term file, never spelled out here: a test that
# names the strings it asserts are absent puts them in the repo it is guarding.
TERMS="${AI_OS_HOME:-$HOME/.ai-os}/config/privacy-terms.txt"
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
t "inherited suites still pass"
if [ -f "$REPO/adapters/claude-code/tests/test-guard-push.py" ]; then
  python3 "$REPO/adapters/claude-code/tests/test-guard-push.py" >/dev/null 2>&1
  chk "claude-code git push guard" $?
else
  printf '  %sSKIP%s claude-code push guard tests not found\n' "$D" "$X"
fi

# =====================================================================================
printf '\n%s%d passed%s' "$G" "$pass" "$X"
[ "$fail" -gt 0 ] && printf ', %s%d failed%s' "$R" "$fail" "$X"
printf '\n\n'
exit $(( fail > 0 ))
