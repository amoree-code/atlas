---
name: ship
description: Take a large piece of work to completion autonomously - frame it, split it into independently shippable phases, then per phase design, build, verify, review with an independent reviewer, push a branch and open a PR, with a feedback block between phases. Use when the user says ship this, run this mission, finish this A-Z, take this to completion, loop until done, or hands over large work he will not review step by step.
---

# Ship

The owner is not reviewing this step by step — that is the whole reason the skill exists.
So **the review happens inside the loop, by an agent that did not write the code**, and
every claim carries the command that proves it. A phase that was not independently
reviewed is not finished, however green it looks.

Merging stays his. Everything up to the merge button is yours.

## Authority

Launching a mission is standing approval to branch, commit, push the feature branch, and
open or update its PR — for every phase, without asking again.

> This is a deliberate, owner-granted narrowing of the charter rule that `git push` needs
> approval every time (decided 2026-10-05, recorded in T-240). It holds **inside a mission
> the owner launched**, and nowhere else. Outside this skill the charter rule stands
> unchanged. If you are unsure whether a mission was actually launched, it wasn't — ask.

**Never, whatever the mission says:** merge a PR · push to `main` · force-push or rewrite
pushed history · add a remote to `~/ocean` or copy private workspace content into the
public repo · write a secret, token or key into any file, commit or PR body · delete a
project, drop a database or run a destructive migration.

Hitting one of these **halts the mission and asks him** — it is the one thing that does.
A failing phase does not halt the mission; a forbidden action does.

## Phase 0 — Frame the mission, once

1. **Think before you decompose.** Invoke `design-thinking` (the problem, the desired
   outcome, success criteria) and `business-logic` (explicit rules, states, permissions,
   exceptions, verifiable acceptance criteria). Both already exist — don't restate that
   reasoning inline here.

2. **Split into phases.** Each phase must be independently shippable, independently
   verifiable, and mergeable alone without breaking `main`. Order them so no phase depends
   on a later one. A phase nobody could merge on its own is two phases or none.

3. **Open the task record** at `~/ocean/brain/04-projects/<project>/tasks/<ID>/task.md`
   before any code — `atlas policy task`, "a task was given is the test". Frontmatter:
   `id` · `title` · `state: active` · `project` · `opened` · `updated` · `artifacts` ·
   `class` · `expected_context`. Sections: `## Objective` · `## Definition of done` ·
   `## Verification` · `## Log` · `## Next action` · `## Blockers`.

4. **Write the phase plan** as `plan.md` beside `task.md`, named in `artifacts:` — never
   inlined into the record. Per phase: outcome, rules, acceptance criteria, the exact
   verification command, the branch name.

5. **Promote only what needs it.** A phase big enough that resuming it cold would mean
   re-deriving context gets its own `T-` record, linked from the umbrella task. Most
   phases don't. Don't scaffold records you won't use.

6. **Show him the phase list before building.** One screen: the phases, in order, one line
   each. This is the last cheap moment to correct the shape of the work — a vague phase
   list produces vague PRs for the rest of the mission.

## The phase loop

Repeat per phase, in order.

1. **Frame the phase.** Restate its outcome, rules and acceptance criteria from `plan.md`.
   If you can't say what would prove it done, you can't start it.

2. **Branch first**, before the first edit. The base is `main` unless this phase builds on
   a phase that shipped blocked — then it is that blocked branch:
   ```bash
   git switch <base> && git pull --ff-only && git switch -c feat/t<nnn>-<slug>
   ```
   House convention is `<type>/t<nnn>-<slug>` — `feat/t238-skill-hub`,
   `fix/t224-lint-graft-helpers`. Branching as an afterthought before pushing is too late.

3. **Build the smallest correct change** — `atlas policy minimal-change`. Does it need to
   exist, does the repo already do it, can an existing abstraction extend in place. Never
   cut validation, authorization, error handling for a case that can really happen, or the
   test that proves the change correct.

4. **Verify for real.** Run the command; report its actual output or the decisive lines.
   Use `atlas observe -- <cmd>` on large runs so failures come back instead of a
   transcript. **`executed` is not `verified`** — never write that a test passed without
   having run it. Delete temporary test files before staging.

5. **Review — the step that stands in for him.** In order:
   - **`verifier` subagent, always.** Read-only, re-derives the result from the filesystem
     and git state, and **must not be the agent that wrote the code**. That separation is
     the gate; dropping it dissolves the whole skill.
   - **`/code-review`** on the diff.
   - **`/security-review`**, but only when the phase touches auth, secrets, user input,
     file paths, or network calls. Not every phase.

   Findings are fixed in this phase, not filed for later. A finding you disagree with gets
   a written reason, not silence.

6. **Fix root causes only.** Never patch a symptom, never swallow an exception to go
   green, never bend production behaviour to satisfy a test. Two honest attempts with the
   ruled-out hypotheses written down, then escalate to `debugger` or `architect` with the
   reason recorded — `atlas policy models`. Escalate on evidence, not on a failure count.

7. **Ship it.** Conventional commit, task id as scope — `feat(T-240): <subject>`. Push the
   branch, then check before creating:
   ```bash
   gh pr list --head <branch>
   ```
   **Never open a second PR for a branch that already has one** — update it.
   - Green → normal PR. Body: what changed, the verification command and its real output,
     what the review caught.
   - Still red after escalation → **draft** PR, title prefixed `[blocked]`, body stating
     exactly what fails and what was ruled out. Record it in `## Blockers` and **continue
     to the next phase** — one bad phase does not stop the mission.
   - A phase building on a blocked one branches from that blocked branch, not `main`, and
     opens its PR with that branch as the base: `gh pr create --base <blocked-branch>`.
     Say so in the body. When the blocked PR is later fixed or merged, retarget the
     stacked one with `gh pr edit <n> --base main` — leaving it based on a merged branch
     makes its diff unreadable.

8. **Write the feedback block** — one per phase, appended to `## Log` and `plan.md`:
   what shipped · what the verification actually proved · what the review caught · **what
   was verified and what was assumed, stated separately** · what the next phase should
   change because of this one. A block, never a transcript.

9. **Checkpoint, then drop the context.**
   ```bash
   atlas tasks checkpoint <ID> --note "what landed, evidence, verification state" \
                               --next "the one next action"
   ```
   Then start the next phase from `task.md` and `plan.md` — **not** from what is still in
   the conversation. Re-read the record; don't carry the last phase's working context into
   the next one. Context must not grow phase over phase.

   Don't call `atlas lifecycle --task <ID>` here expecting a routing verdict: without
   `--complete --verification passed` it only ever returns `CONTINUE`
   (`packages/core/src/interfaces/cli/governance-command.ts`). The reset above is your own
   discipline, not something the CLI decides for you.

## Stopping

Stop when every phase has shipped, or when a blocker makes all remaining phases
impossible — **not** when one phase fails. Then run the completion sequence from
`atlas policy task`: final verification first, then

```bash
atlas tasks verify <ID>
atlas lifecycle --task <ID> --complete --verification passed|failed
atlas tasks complete <ID>
```

`atlas lifecycle` only prints a verdict — **`atlas tasks complete` is what actually moves
the record out of `active`.** Skipping it leaves a finished mission looking unfinished.

Then the summary, then `memory-curator`, then `task-scribe`. **Bookkeeping is delegated,
never run on the strong model.**

Close with the mission report: every phase, its PR number and link, green or draft, and
the one thing left for him — merge, in this order.

## Rules

- **An unreviewed phase is not a finished phase.** The `verifier` gate is not optional and
  is never run by the agent that wrote the code.
- **Never merge, never push to `main`.** The merge button is the owner's, every time.
- Say what was **verified** versus what was **assumed**, separately, in every phase report.
- A phase that fails ships as a draft PR and the loop continues — it does not halt the
  mission and it does not quietly get skipped.
- Don't let context accumulate across phases. Checkpoint and reset; the record is the
  memory.
- No secrets in any file, commit, PR body or task record. Report `.env` key names only.
