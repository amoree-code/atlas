---
name: use-browser
description: Open a supplied URL, understand the user's requested outcome from the live page, complete the browser task, and verify the result.
version: 1.0.0
category: core
---

# Use Browser

Use when the user gives a URL and asks the agent to complete, fill, test, submit, or otherwise operate the page.

Use Atlas's `atlas browser` capability through the terminal as the default browser backend. Do not switch to `claude-in-chrome`, an extension, or another browser connector unless the user explicitly asks for that backend. If Atlas cannot detect or open a browser, report the exact command result and stop; do not ask the user to install a different browser extension as the first workaround.

## Workflow

1. Treat the URL as the starting location, not as permission to perform every possible action on the site.
2. Open or reconnect to an Atlas browser session with a persistent profile. Navigate to the URL.
3. Inspect the live page with `observe`, `read`, and targeted `extract`. Identify the page's current state, the user's intended outcome, required fields, available controls, and a concrete success signal.
4. Build the smallest step sequence that reaches the requested outcome. Prefer stable labels, roles, names, ids, and visible text. Use editor selectors for `contenteditable`, CodeMirror/Monaco containers, and `frame >>> editor` for same-origin iframe editors.
5. Execute through Atlas browser operations or a bounded browser task file. After every state-changing step, verify the live post-condition. Stop if the page state contradicts the plan.
6. For forms, tests, purchases, uploads, messages, or other externally visible mutations, keep the existing Atlas approval gate. Ask for confirmation only at the final consequential action when approval is not already present.
7. If a field is ambiguous, required data is missing, authentication is needed, or the page reports failure, stop with the exact blocker. Do not invent personal, financial, legal, academic, or credential data.
8. Report the outcome, the verified success signal, and any unverified or blocked step. Close the browser session only if the user requested cleanup; otherwise preserve it for continuation.

## Atlas execution shape

Use the browser capability's session lifecycle and task runner:

```text
atlas browser detect
atlas browser open --profile <profile>
atlas browser navigate <session-id> <URL> --approve
atlas browser observe <session-id>
atlas browser read <session-id>
atlas browser run <session-id> <task-file> --approve
```

Use direct operations for discovery and a bounded JSON task for repeatable execution. Keep task files small, set `retries` to 0–2, and never use retries to repeat an irreversible action blindly. The runner caps retries at three and stops on failed verification.

## Completion contract

A task is complete only when the requested outcome is visible in live page state: a success message, changed status, expected navigation, submitted result, or another explicit post-condition. A click or lack of error is not proof by itself.
