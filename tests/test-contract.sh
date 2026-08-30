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

t "the Claude rules fragment lives in the Claude plugin"
[ -f "$REPO/plugins/claude-code/rules-fragment.md" ]
chk "plugins/claude-code/rules-fragment.md exists" $?
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

t "THE SKILL GATE: 8 skills render equivalent to the committed goldens"
# This gate began as a migration check: the canonical bodies had to render equivalent to
# the hand-maintained copy in the runtime layer. That copy was rendered with the real
# user's profile — it carried their org folders and VCS handle — so it could never live
# here, and it retires with ~/.ai. The proof is preserved by rendering against a fictional
# fixture profile and diffing the committed goldens instead: same eight skills, same
# renderer, same client conventions, no private data and no runtime dependency.
GW="$TMP/goldenws"; mkdir -p "$GW/config"
cp "$REPO/tests/fixtures/profile.yaml" "$GW/config/profile.yaml"
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
# THE STEP 9 GATE: memory is a CORE capability. Core must not know any client exists.
t "memory engine: core carries no client knowledge"
# A client name anywhere in the engine is the defect this split exists to remove.
hits=$(grep -Eic 'claude|codex|gemini|cursor|opencode' "$CLI/ai-os-memory" || true)
[ "$hits" -eq 0 ];   chk "0 client references in cli/ai-os-memory" $?
grep -q 'if client' "$CLI/ai-os-memory"
[ $? -ne 0 ];        chk "no branch on client identity" $?

t "memory engine: the Claude facts live in the Claude plugin, once"
AD="$REPO/adapters/claude-code/ai-memory-mounts"
[ -x "$AD" ];                                    chk "claude-code ships a mounts adapter" $?
grep -q '\.claude' "$AD";                        chk "it owns the ~/.claude/projects path" $?
grep -q 're\.sub' "$AD";                         chk "it owns the cwd-slug rule" $?
# The slug rule must exist in exactly one place, or the split leaked.
n=$(grep -rl 'projects.*<cwd-slug>\|\[/\.\]' "$REPO/cli" "$REPO/adapters" 2>/dev/null | wc -l)
[ "$n" -eq 1 ];                                  chk "the slug rule exists in exactly one file" $?

t "memory engine: a NON-Claude client gets the whole engine"
# The real proof of a client-agnostic core: a client that does not exist, with no Claude
# anywhere in the environment, consuming the engine through the same declared contract.
MW="$TMP/mem-ws"; MP="$TMP/mem-plugins"; MA="$TMP/mem-adapters"
AI_OS_HOME="$MW" "$CLI/ai-os-init" >/dev/null 2>&1
mkdir -p "$MP/testclient" "$MA/testclient" "$TMP/tc-home/proj-a" "$TMP/tc-home/proj-b"
cat > "$MP/testclient/plugin.yaml" <<EOF
plugin: testclient
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
export AI_OS_PLUGINS="$MP" AI_OS_ADAPTERS="$MA"

out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach 2>&1); rc=$?
[ "$rc" -eq 0 ];                                 chk "core attaches a non-Claude client's mounts" $?
[ -L "$TMP/tc-home/proj-a/memory" ];             chk "mount a is now a symlink" $?
# Compared by inode: the target string may differ harmlessly from $MW (a trailing slash
# in TMPDIR, a symlinked /tmp) while pointing at exactly the same store.
[ -L "$TMP/tc-home/proj-b/memory" ] && [ "$TMP/tc-home/proj-b/memory" -ef "$MW/memory" ]
chk "mount b resolves to the canonical store" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" status 2>&1)
echo "$out" | grep -q 'linked'                   ; chk "status reports it linked" $?
AI_OS_HOME="$MW" "$CLI/ai-os-memory" doctor >/dev/null 2>&1
chk "doctor passes on a freshly attached non-Claude workspace" $?
env | grep -qi 'claude' && claude_in_env=1 || claude_in_env=0
[ "$claude_in_env" -eq 0 ] || [ -z "${AI_OS_PLUGINS##*mem-plugins}" ]
chk "the engine resolved no Claude plugin at all" $?

t "memory engine: attach --here asks the plugin which mount serves this directory"
# Step 10 needs exact parity with the historical `link`: one directory, not all of them.
mkdir -p "$TMP/tc-home/proj-here"
out=$(cd "$TMP/tc-home/proj-here" && AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --here 2>&1)
[ -L "$TMP/tc-home/proj-here/memory" ];          chk "--here attached the current directory" $?
[ ! -e "$TMP/tc-home/proj-d/memory" ];           chk "   ...and only that one" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --here /some/path 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "--here with a PATH is refused" $?
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach --bogus 2>&1); rc=$?
[ "$rc" -eq 2 ];                                 chk "an unknown option is refused, not ignored" $?
grep -q 'cwd' "$CLI/ai-os-memory";               chk "core resolves cwd through the plugin, not a rule of its own" $?

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
sed 's/verified: true }/verified: false }/' "$MP/testclient/plugin.yaml" > "$TMP/pv" \
  && mv "$TMP/pv" "$MP/testclient/plugin.yaml"
rm -f "$TMP/tc-home/proj-a/memory" "$TMP/tc-home/proj-b/memory"
out=$(AI_OS_HOME="$MW" "$CLI/ai-os-memory" attach 2>&1)
echo "$out" | grep -q 'no client declares memory mounts'
chk "core refuses to call an unverified integration" $?
[ ! -e "$TMP/tc-home/proj-a/memory" ];           chk "   ...and wrote nothing" $?

t "memory engine: the registry rejects an invented integration point"
mkdir -p "$TMP/bad-plugins/badint"
cat > "$TMP/bad-plugins/badint/plugin.yaml" <<'EOF'
plugin: badint
name: Bad Integration
contract: 1
client: { detect: [/nonexistent], consumer_verified: true }
provides:
  rules: { path: ~/.badint/RULES.md, format: markdown, verified: true }
writes: [rules]
integrates:
  memory.everything: { command: x, format: newline-paths, verified: true }
EOF
out=$(AI_OS_PLUGINS="$TMP/bad-plugins" "$CLI/ai-os-plugin" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "an unknown integration point fails" $?
echo "$out" | grep -q 'may not invent one';      chk "   ...with a reason, not a guess" $?

mkdir -p "$TMP/bad-plugins2/badcmd"
sed 's|memory.everything: { command: x,|memory.mounts: { command: ../../etc/x,|' \
  "$TMP/bad-plugins/badint/plugin.yaml" | sed 's/plugin: badint/plugin: badcmd/' \
  > "$TMP/bad-plugins2/badcmd/plugin.yaml"
out=$(AI_OS_PLUGINS="$TMP/bad-plugins2" "$CLI/ai-os-plugin" doctor 2>&1); rc=$?
[ "$rc" -ne 0 ];                                 chk "a command escaping its adapter dir fails" $?
unset AI_OS_PLUGINS AI_OS_ADAPTERS

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
  mkdir -p "$1/config"; printf 'ai_os_repo: %s\n' "$2" > "$1/config/settings.yaml"
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
got=$(sed -n 's/^ai_os_repo:[[:space:]]*//p' "$IW/config/settings.yaml" | head -1)
[ "$got" = "$REPO" ];                           chk "init recorded its own actual location" $?
# 12. explicit value survives
sed 's|^ai_os_repo:.*|ai_os_repo: ~/deliberately/elsewhere|' "$IW/config/settings.yaml" > "$TMP/x" \
  && mv "$TMP/x" "$IW/config/settings.yaml"
out=$(AI_OS_HOME="$IW" "$CLI/ai-os-init" 2>&1)
got=$(sed -n 's/^ai_os_repo:[[:space:]]*//p' "$IW/config/settings.yaml" | head -1)
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
grep -q 'RUNTIME = AI_OS_HOME / "runtime"' "$SY"
chk "runtime state resolves under it" $?
grep -q 'STATE = RUNTIME / "state"' "$SY";           chk "   ...state" $?
grep -q 'BACKUPS = RUNTIME / "backups"' "$SY";       chk "   ...backups" $?

t "the retired runtime layer holds no tooling"
# ~/.ai kept the engine, then a shim, then nothing. What remains is the frozen archive.
for gone in bin skills rules tasks docs manifest capabilities.yaml; do
  [ ! -e "$HOME/.ai/$gone" ];                        chk "~/.ai/$gone is gone" $?
done
[ -d "$HOME/.ai/workspace" ];                        chk "the frozen archive is still there" $?
n=$(find "$HOME/.ai" -maxdepth 1 -type l | wc -l | tr -d ' ')
[ "$n" -eq 0 ];                                      chk "no stale symlinks into the archive" $?

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
