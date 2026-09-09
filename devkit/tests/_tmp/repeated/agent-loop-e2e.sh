#!/usr/bin/env bash
# tests/_tmp/repeated/agent-loop-e2e.sh — real agent-loop validation, not a contract test.
#
# Proves the AI-facing interface end to end: an agent (this script stands in for one)
# drives observe -> decide -> `atlas run step` -> verify -> continue through the real
# Browser Control capability, reaching a genuinely verified `completed` state, AND
# separately hits the execute-with-approval boundary and is refused, not self-approved.
#
# Nothing here is a permanent contract check (see tests/test-contract.sh for that). This
# is disposable and reusable per dev-mode.md / tests/_tmp/README.md: rerun it any time the
# agent-facing Run/Capability loop needs to be reconfirmed after a real change, instead of
# writing a new one-off script.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CLI="$REPO/cli"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/atlas-agent-e2e.XXXXXX")"
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP"' EXIT

G=$'\033[32m'; R=$'\033[31m'; Y=$'\033[33m'; D=$'\033[2m'; X=$'\033[0m'
[ -t 1 ] || { G=; R=; Y=; D=; X=; }
say() { printf '\n%s%s%s\n' "$D" "$1" "$X"; }
ok()  { printf '  %sOK%s   %s\n' "$G" "$X" "$1"; }
bad() { printf '  %sFAIL%s %s\n' "$R" "$X" "$1"; fail=1; }
fail=0

export ATLAS_HOME="$TMP/home"
"$CLI/atlas-init" >/dev/null 2>&1
python3 - "$ATLAS_HOME" <<'PYEOF'
import sys, pathlib
f = pathlib.Path(sys.argv[1]) / "system/config/authority.yaml"
f.write_text(f.read_text().replace("capabilities: {}", "capabilities:\n  browser: execute"))
PYEOF
export ATLAS_BROWSER_RUNTIME="$TMP/browser-runtime"

WEB="$TMP/web"; mkdir -p "$WEB"
cat > "$WEB/start.html" <<'HTMLEOF'
<html><body>
<h1 id="h">Task</h1>
<p id="p">enter the code and continue</p>
<input id="q" type="text">
<a id="go" href="done.html">Continue</a>
</body></html>
HTMLEOF
cat > "$WEB/done.html" <<'HTMLEOF'
<html><body><h1 id="r">Task complete</h1></body></html>
HTMLEOF

if ! (cd "$REPO/capabilities/browser" && echo '{}' | ./browser detect >/dev/null 2>&1); then
  printf '%sSKIP%s no browser provider available on this machine\n' "$Y" "$X"
  exit 0
fi

# =====================================================================================
say "run 1 — the agent completes a real multi-step task, verified at every step"
out=$("$CLI/atlas-run" create --max-steps 10 \
  --scope 'browser.open,browser.navigate,browser.read,browser.extract,browser.type,browser.click' \
  --task DEMO-AGENT-TASK)
RUN=$(echo "$out" | grep -oE 'run-[0-9a-f-]+' | head -1)
[ -n "$RUN" ] && ok "run created: $RUN" || bad "run creation failed"

step() { # capability.op, json, [extra flags...]
  "$CLI/atlas-run" step "$RUN" "$1" --json "$2" "${@:3}"
}

out=$(step browser.open '{}');                                                    rc=$?
echo "$out" | grep -q 'verified  deterministic'; [ $? -eq 0 ] && ok "open: executed and verified"  || bad "open did not verify"

out=$(step browser.navigate "{\"url\":\"file://$WEB/start.html\"}");              rc=$?
echo "$out" | grep -q 'verified  deterministic'; [ $? -eq 0 ] && ok "navigate: executed and verified" || bad "navigate did not verify"

out=$(step browser.read '{}');                                                    rc=$?
echo "$out" | grep -q 'enter the code'; [ $? -eq 0 ] && ok "read: agent observes real page text" || bad "read did not return page text"

out=$(step browser.extract '{"selector":"#h"}');                                  rc=$?
echo "$out" | grep -q 'Task'; [ $? -eq 0 ] && ok "extract: agent pulls a specific element" || bad "extract failed"

out=$(step browser.type '{"selector":"#q","text":"42"}');                         rc=$?
echo "$out" | grep -q 'verified  deterministic'; [ $? -eq 0 ] && ok "type: field value verified by live re-read" || bad "type did not verify"

out=$(step browser.click '{"selector":"#go","expect":{"url_contains":"done.html"}}' --complete-on-verified)
echo "$out" | grep -q 'completed  browser.click verified'
[ $? -eq 0 ] && ok "click: real navigation, live-state verified, run COMPLETED" || bad "run did not reach completed"

st=$("$CLI/atlas-run" status "$RUN")
echo "$st" | grep -q '"status": "completed"';  [ $? -eq 0 ] && ok "status confirms terminal state: completed" || bad "status does not show completed"
n_verified=$(echo "$st" | grep -c '"verified": true')
[ "$n_verified" -ge 4 ] && ok "$n_verified steps independently verified (not model-asserted)" || bad "fewer verified steps than expected"

out=$(step browser.read '{}'); rc=$?
[ "$rc" -ne 0 ] && ok "a step after completion is refused, not executed" || bad "completed run accepted another step"

ATLAS_CAPABILITIES="$REPO/capabilities" "$CLI/atlas-capability" invoke browser.close --json '{}' >/dev/null 2>&1

# =====================================================================================
say "run 2 — the approval boundary actually stops the agent, no self-approval"
out=$("$CLI/atlas-run" create --max-steps 5 --scope 'browser.open,browser.navigate,browser.submit' \
  --task DEMO-AGENT-APPROVAL)
RUN2=$(echo "$out" | grep -oE 'run-[0-9a-f-]+' | head -1)
"$CLI/atlas-run" step "$RUN2" browser.open --json '{}' >/dev/null 2>&1
out=$("$CLI/atlas-run" step "$RUN2" browser.submit --json '{"selector":"#go"}' </dev/null); rc=$?
echo "$out" | grep -q 'needs-approval'
[ $? -eq 0 ] && ok "submit (execute-with-approval) halts the agent at needs-approval" || bad "approval boundary did not fire"
[ "$rc" -eq 5 ] && ok "  ...with its own distinct exit code (5)" || bad "wrong exit code for needs-approval"
st2=$("$CLI/atlas-run" status "$RUN2")
echo "$st2" | grep -q '"status": "needs-approval"'; [ $? -eq 0 ] && ok "  ...recorded in the run itself" || bad "run record missing needs-approval"
out=$("$CLI/atlas-run" step "$RUN2" browser.open --json '{}' 2>&1); rc=$?
[ "$rc" -ne 0 ] && ok "the agent cannot push past needs-approval on its own — no self-approval" || bad "agent bypassed the approval boundary"
ATLAS_CAPABILITIES="$REPO/capabilities" "$CLI/atlas-capability" invoke browser.close --json '{}' >/dev/null 2>&1

# =====================================================================================
say "result"
if [ "$fail" -eq 0 ]; then
  printf '  %sALL OK%s — the agent loop works through the existing Run + Capability + Verification system\n\n' "$G" "$X"
  exit 0
else
  printf '  %sFAILURES ABOVE%s\n\n' "$R" "$X"
  exit 1
fi
