# Agent handoff record — template

**Copy this file, fill it in, hand it over.** One reusable record that lets any AI executor
hand work back to any AI reviewer or planner — Codex, Claude, or a future client — without
the owner having to re-explain what happened.

```
User → Planner AI → Executor AI → Handoff Result → Reviewer AI → Owner summary / next plan
```

Any client may sit in any seat. The only condition for taking part is writing and reading
this same record.

**What this is not.** A written format, and nothing more:

- **Not hidden agent-to-agent messaging.** Agents do not talk secretly through Atlas. They
  exchange explicit written records the owner can read, keep and inspect.
- **Not a Workflow Engine.** It describes work that already happened; it sequences nothing.
- **Not an Agent Runtime.** Nothing here runs, schedules, or dispatches anything.
- **Not Agent Orchestration.** No agent is assigned, coordinated or triggered by this file.

Nothing parses it, no CLI reads it, no schema validates it. A blank template is not a task
artifact; a *filled-in* record may be kept beside the task it describes, or pasted straight
into the next AI's prompt.

## Rules for whoever fills this in

- **The owner must be able to inspect every handoff.** Write for a human reader first.
- **A completed checkbox is not proof.** Evidence points at something real — a file, a
  command and its output, a test result, a run id, a record.
- **If verification was not run, say why.** `executed ≠ verified` — an unverified change is
  reported as unverified, never as done.
- **If scope was exceeded, say so clearly** and name every file touched outside the allowed
  list. A quiet overrun is the one failure this record exists to prevent.
- **If the public repo was touched, say exactly what changed** — path by path.
- **Never include secrets, tokens, API keys, passwords or connection strings.** Report key
  *names* only, never values. If a secret was needed and missing, say that instead.
- Leave a field as `none`, `n/a` or `unknown` when that is the truth. An honestly empty
  field is worth more than a confident guess.

---

## 1. Handoff metadata

```
handoff_id:    <YYYYMMDD-NNN or a short unique id>
date:          <YYYY-MM-DD>
project:       <registry name, or - for none>
task_id:       <SCOPE-NNN, a backlog line, or - if neither exists>
planner_ai:    <who framed the work — client + model, or "owner" if unplanned>
executor_ai:   <who did the work — client + model>
reviewer_ai:   <who is meant to review this — client + model, or "unassigned">
owner:         <owner name>

status:                <optional — draft | waiting-owner | approved | sent | returned | reviewed | blocked | stopped | closed>
gate:                  <optional — plan-scope | execute | review | next-step | remote-or-destructive | resume>
owner_action_required: <optional — none | approve | reject | choose-reviewer | resume | stop>
```

The last three lines are **optional**. Leave them out for an ordinary hand-pasted handoff.
Fill them in when the record is going to be **kept beside a task**, because a stored record is
read later with none of the conversation around it and has to say for itself where it got to.
Nothing reads these fields but a person.

## 2. Original request

```
user_request:            <what the owner actually asked for, in their terms>
planner_prompt_or_scope: <the brief the executor worked from; "same as above" if direct>
allowed_files:           <every path the executor was permitted to change>
forbidden_scope:         <what was explicitly off limits>
approval_status:         <approved in advance | approved per action | not approved>
```

## 3. Execution summary

```
status:               <complete | partial | blocked | abandoned>
changed_files:        <path — one line each, with what changed>
created_files:        <path — one line each, or none>
deleted_files:        <path — one line each, or none>
commands_run:         <the real commands, in order; never a paraphrase>
tools_used:           <editors, capabilities, MCP servers, external services>
implementation_notes: <decisions taken while working, and what was deliberately not done>
```

## 4. Verification

```
verification_run:        <yes | no — and if no, why not>
verification_result:     <the actual output or its decisive lines; never "looks fine">
tests_passed:            <count or names, or n/a>
tests_failed:            <count or names, or none>
unverified_claims:       <every statement above that was not proved — list them plainly>
known_baseline_failures: <failures that already existed before this work>
```

## 5. Scope control

```
only_allowed_files_changed:   <yes | no — if no, name every extra file and why>
public_repo_touched:          <no | yes — if yes, exactly what changed, path by path>
private_workspace_touched:    <no | yes — which areas>
runtime_touched:              <no | yes — runtime/ is derived state; explain>
secrets_touched:              <no | yes — key names only, never values>
approvals_needed_but_missing: <push, delete, migration, install, or none>
```

## 6. Reviewer section

*Filled by the reviewer AI, not the executor. Left blank on handoff.*

```
reviewer_verdict:       <approved | approved with findings | changes required | blocked>
reviewer_findings:      <what is wrong or unproven, most serious first>
risks:                  <what could break, and where it would show>
contradictions:         <anything conflicting with roadmap, charter, state, or a decision>
recommended_next_step:  <the single next action, concrete enough to act on>
```

## 7. Owner summary

*Plain language, no jargon. This is the part the owner reads first.*

```
what_changed:            <two or three lines, in ordinary words>
what_is_safe_to_trust:   <what was actually verified, and by what evidence>
what_needs_owner_decision: <choices only the owner can make, each stated as a question>
next_prompt_needed:      <the prompt that would continue this work, ready to paste>
```

## 8. Approvals

*Optional, and only the owner writes these. Leave the section out entirely when the handoff
carried no approval gate.*

```
- date:         <YYYY-MM-DD>
  gate:         <which gate this approves>
  scope:        <the exact files, actions or next hop approved — named, not summarised>
  owner_words:  "<the owner's own words, verbatim>"
  recorded_by:  <owner | an AI transcribing the owner's words verbatim>
```

- **A missing approval is a refusal.** Silence, being offline, and a previous approval are
  none of them approval.
- **One approval covers one gate and one scope.** A wider or riskier action needs its own line,
  and remote, destructive, credential, install, publish, push, delete and migration actions
  always do.
- An AI may write the *request*; only the owner gives the *grant*. A transcribed approval says
  so in `recorded_by` and quotes the owner exactly — a paraphrase is not an approval.

## 9. Result packet — state transfer without context transfer

*The compact form. Fill this in whenever the work is being handed BACK — worker to parent,
executor to reviewer, session to session, one provider to another.*

A handoff moves **state**, never context. The receiving side gets what it needs to decide
and act; it does not get the transcript that produced it, because re-reading that transcript
is the cost this record exists to avoid. The same nine fields serve every hop, which is why
a subagent's return and a cross-provider handoff have one shape rather than two.

```
goal:            <what this hop was asked to establish or change>
findings:        <what is now known that was not known before — the answer, not the search>
evidence:        <what proves each finding: a path, a command and its output, a test result,
                  a run id. Never "looks fine">
confidence:      <high | medium | low — per finding where they differ>
paths:           <the files and resources the next step will need, and nothing else>
constraints:     <what the next step must not do, and why>
recommendation:  <the single next action, concrete enough to start cold>
unresolved:      <what was not settled, and what would settle it>
verification:    <run | not run — and if not run, why. `executed` is not `verified`>
```

**No transcripts.** Not the conversation, not the full tool output, not the reasoning that
led to a finding. If a raw artifact matters, name where it is — a file path, or an
`atlas observe` id — and let the reader fetch the part they need.

**An honestly empty field beats a confident guess.** `none`, `n/a` and `unknown` are all
real answers here.
